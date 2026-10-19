"""Versioned prompt files (SPEC §10).

A prompt file is `<name>.v<version>.md`: YAML front matter, then `# system` and `# user`
sections with `{{variable}}` placeholders. Variables listed under `truncatable` may be
cut to fit the token budget; everything else (the instructions) never is.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^# (system|user)\s*$", re.MULTILINE)
_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_FILENAME = re.compile(r"^(?P<name>[\w-]+)\.v(?P<version>\d+)\.md$")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    purpose: str
    model_role: str
    system: str
    user: str
    truncatable: frozenset[str] = field(default_factory=frozenset)

    @property
    def variables(self) -> set[str]:
        return set(_VAR.findall(self.system)) | set(_VAR.findall(self.user))

    def render(self, variables: Mapping[str, str]) -> tuple[str, str]:
        missing = self.variables - set(variables)
        if missing:
            raise PromptError(f"prompt {self.name}.v{self.version} missing {sorted(missing)}")

        # Single pass, so text inside a variable (e.g. a log) is never re-substituted.
        def sub(text: str) -> str:
            return _VAR.sub(lambda m: str(variables[m.group(1)]), text)

        return sub(self.system), sub(self.user)


def parse_prompt(text: str, source: str = "<string>") -> Prompt:
    match = _FRONT_MATTER.match(text.replace("\r\n", "\n"))
    if not match:
        raise PromptError(f"{source}: missing YAML front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    parts = _SECTION.split(match.group(2))
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    for key in ("name", "version"):
        if key not in meta:
            raise PromptError(f"{source}: front matter needs '{key}'")
    if "system" not in sections or "user" not in sections:
        raise PromptError(f"{source}: needs '# system' and '# user' sections")
    return Prompt(
        name=str(meta["name"]),
        version=str(meta["version"]),
        purpose=str(meta.get("purpose", "")),
        model_role=str(meta.get("model_role", "primary")),
        system=sections["system"],
        user=sections["user"],
        truncatable=frozenset(meta.get("truncatable") or ()),
    )


class PromptStore:
    def __init__(self, directory: Path = PROMPTS_DIR) -> None:
        self._dir = directory
        self._cache: dict[str, Prompt] = {}

    def load(self, name: str, version: str | None = None) -> Prompt:
        """Load `name` at `version`, or the highest version present."""
        key = f"{name}@{version}"
        if key not in self._cache:
            path = self._find(name, version)
            prompt = parse_prompt(path.read_text(encoding="utf-8"), source=path.name)
            expected = _FILENAME.match(path.name)
            if expected is None or (prompt.name, prompt.version) != (name, expected["version"]):
                raise PromptError(f"{path.name}: front matter does not match the file name")
            self._cache[key] = prompt
        return self._cache[key]

    def _find(self, name: str, version: str | None) -> Path:
        candidates: list[tuple[int, Path]] = []
        for path in self._dir.glob(f"{name}.v*.md"):
            m = _FILENAME.match(path.name)
            if m and m.group("name") == name:
                candidates.append((int(m.group("version")), path))
        if version is not None:
            candidates = [c for c in candidates if c[0] == int(version)]
        if not candidates:
            raise PromptError(f"prompt {name} (version {version or 'latest'}) not found")
        return max(candidates)[1]
