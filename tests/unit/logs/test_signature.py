from genie_copilot.logs.masking import Masker
from genie_copilot.logs.models import ExceptionInfo, Frame, RawLog
from genie_copilot.logs.parser import parse
from genie_copilot.logs.signature import compute, normalise, signature_methods

from .conftest import IN_HOUSE, RULES, load


def _variant(name: str, replacements: dict[str, str]) -> RawLog:
    raw = load(name)
    lines = []
    for line in raw.lines:
        for old, new in replacements.items():
            line = line.replace(old, new)
        lines.append(line)
    return raw.model_copy(update={"lines": lines})


def _sig(raw: RawLog, user: str) -> str:
    parsed = parse(raw, Masker(RULES, extra_terms=[user]), IN_HOUSE)
    assert parsed is not None
    return parsed.error_signature


def test_same_error_different_run_user_time_same_signature() -> None:
    a = load("simple_ioexception.log")
    b = _variant(
        "simple_ioexception.log",
        {
            "jdoe": "kpatel",
            "2026-10-01": "2026-11-15",
            "09:14": "17:02",
            "7f3c2a1e-9b8d-4c6e-a1f2-3d4e5f6a7b8c": "00000000-1111-2222-3333-444444444444",
            "batch_20261001": "batch_20261115",
            "line 88": "line 90",
        },
    )
    assert _sig(a, "jdoe") == _sig(b, "kpatel")


def test_different_exception_different_signature() -> None:
    a = load("simple_ioexception.log")
    b = _variant(
        "simple_ioexception.log", {"System.IO.IOException": "System.UnauthorizedAccessException"}
    )
    assert _sig(a, "jdoe") != _sig(b, "jdoe")


def test_different_in_house_frames_different_signature() -> None:
    a = load("simple_ioexception.log")
    b = _variant("simple_ioexception.log", {"ReadInvoicesStep": "ReadOrdersStep"})
    assert _sig(a, "jdoe") != _sig(b, "jdoe")


def test_normalise() -> None:
    message = (
        "Timeout 2026-10-01T09:14:02Z for 'C:\\data\\x.xlsx' "
        "id 7f3c2a1e-9b8d-4c6e-a1f2-3d4e5f6a7b8c "
        "order 123456 user <ID_3> mail a@b.com code 42"
    )
    assert normalise(message) == "Timeout _ for _ id _ order _ user <ID> mail _ code 42"


def test_signature_methods_fall_back_outward() -> None:
    root = ExceptionInfo(exception_type="System.X", message="m", frames=[Frame(method="System.A")])
    outer = ExceptionInfo(
        exception_type="Genie.E",
        message="m",
        frames=[Frame(method=f"Genie.F{i}", in_house=True) for i in range(5)],
        inner=[root],
    )
    assert signature_methods(outer) == ["Genie.F0", "Genie.F1", "Genie.F2"]
    assert len(compute(outer)) == 16
