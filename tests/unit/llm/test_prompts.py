from pathlib import Path

import pytest

from genie_copilot.llm.prompts import PromptError, PromptStore, parse_prompt

from .conftest import DIAG_PROMPT


def test_parse_and_render() -> None:
    prompt = parse_prompt(DIAG_PROMPT)
    assert (prompt.name, prompt.version, prompt.truncatable) == ("diag", "2", {"log"})
    assert prompt.variables == {"bot", "log"}
    system, user = prompt.render({"bot": "bot-a", "log": "L1"})
    assert system.startswith("Classify")
    assert "Bot: bot-a" in user and "<log>\nL1\n</log>" in user


def test_missing_variable_is_an_error() -> None:
    with pytest.raises(PromptError, match=r"missing \['log'\]"):
        parse_prompt(DIAG_PROMPT).render({"bot": "bot-a"})


def test_variable_content_is_not_resubstituted() -> None:
    _, user = parse_prompt(DIAG_PROMPT).render({"bot": "{{log}}", "log": "x"})
    assert "Bot: {{log}}" in user


def test_store_loads_latest_version(tmp_path: Path) -> None:
    for v in (1, 2, 10):
        text = DIAG_PROMPT.replace("version: 2", f"version: {v}")
        (tmp_path / f"diag.v{v}.md").write_text(text)
    store = PromptStore(tmp_path)
    assert store.load("diag").version == "10"
    assert store.load("diag", "2").version == "2"
    with pytest.raises(PromptError, match="not found"):
        store.load("diag", "3")


def test_front_matter_must_match_filename(tmp_path: Path) -> None:
    (tmp_path / "diag.v3.md").write_text(DIAG_PROMPT)  # says version 2
    with pytest.raises(PromptError, match="does not match"):
        PromptStore(tmp_path).load("diag")


@pytest.mark.parametrize(
    "text",
    [
        "# system\nx\n# user\ny",
        "---\nname: a\n---\n# system\nx",
        "---\nversion: 1\n---\n# system\nx\n# user\ny",
    ],
)
def test_malformed_prompts(text: str) -> None:
    with pytest.raises(PromptError):
        parse_prompt(text)


def test_packaged_smoke_prompt_loads() -> None:
    prompt = PromptStore().load("smoke")
    assert prompt.variables == {"word"}
