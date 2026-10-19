import pytest

from genie_copilot.logs.masking import Masker
from genie_copilot.logs.parser import build_window, find_first_error, is_in_house, parse

from .conftest import IN_HOUSE, RULES, expected, load, log_names


def test_every_fixture_has_an_expectation() -> None:
    assert set(log_names()) == set(expected())


@pytest.mark.parametrize("name", log_names())
def test_golden(name: str) -> None:
    want = expected()[name]
    parsed = parse(load(name), Masker(RULES), IN_HOUSE)
    if want is None:
        assert parsed is None
        return
    assert parsed is not None
    assert parsed.error_line_id == want["error_line_id"]
    assert [e.exception_type for e in parsed.chain()] == want["chain"]
    root = parsed.root
    assert len(root.frames) == want["root_frames"]
    assert [f.method for f in root.frames if f.in_house] == want["root_in_house"]
    assert len(parsed.error_signature) == 16
    assert any(line.id == parsed.error_line_id for line in parsed.window)


def test_frames_carry_file_and_line() -> None:
    parsed = parse(load("simple_ioexception.log"), Masker(RULES), IN_HOUSE)
    assert parsed is not None
    frame = parsed.frames[2]
    assert frame.method == "Genie.Bot.Excel.WorkbookReader.Open"
    assert frame.file == r"D:\build\genie\src\Excel\WorkbookReader.cs"
    assert frame.line == 41
    assert parsed.frames[0].file is None and not parsed.frames[0].in_house


def test_inner_chain_frames_assigned_innermost_first() -> None:
    parsed = parse(load("inner_chain.log"), Masker(RULES), IN_HOUSE)
    assert parsed is not None
    outer, http, socket = parsed.chain()
    assert [f.method for f in socket.frames] == [
        "System.Net.Sockets.Socket.Connect",
        "System.Net.Http.HttpConnectionPool.ConnectAsync",
    ]
    assert [f.method for f in http.frames][-1] == "Genie.Bot.Payments.PaymentApi.Post"
    assert outer.frames[0].method == "Genie.Bot.Steps.PostPaymentsStep.Execute"
    assert http.message.startswith("Response status code does not indicate success: 503")
    assert "<IP_1>" in socket.message


def test_multiline_message_kept() -> None:
    parsed = parse(load("multiline_message.log"), Masker(RULES), IN_HOUSE)
    assert parsed is not None
    assert parsed.message.splitlines()[0] == "Input file has 3 invalid rows:"
    assert "row 9: amount missing" in parsed.message
    assert "<ISIN_1>" in parsed.message


def test_error_without_trace_uses_line_text() -> None:
    parsed = parse(load("error_without_trace.log"), Masker(RULES), IN_HOUSE)
    assert parsed is not None
    assert parsed.exception_type == "Unknown"
    assert parsed.message.startswith("Licence server licence.example-bank.internal returned")


def test_window_is_bounded_and_numbered() -> None:
    lines = [f"2026-10-01 10:00:00 INFO line {i}" for i in range(1000)]
    lines[600] = "2026-10-01 10:00:00 ERROR boom"
    assert find_first_error(lines) == 600
    window = build_window(lines, 600, Masker(), radius=200)
    assert [w.id for w in window][:1] == [401] and window[-1].id == 801
    assert window[200].level == "ERROR"
    assert window[0].ts is not None and window[0].ts.tzinfo is not None


def test_window_clipped_at_edges() -> None:
    window = build_window(["a", "b", "c"], 0, Masker(), radius=200)
    assert [w.id for w in window] == [1, 2, 3]


def test_prose_mentioning_an_exception_is_not_a_header() -> None:
    lines = ["INFO retry policy handles System.TimeoutException gracefully", "INFO ok"]
    assert find_first_error(lines) is None


def test_default_in_house_rule() -> None:
    assert is_in_house("Genie.Bot.Run", ())
    assert not is_in_house("System.IO.File.Open", ())
    assert not is_in_house("Microsoft.Win32.Registry.Get", ())
    assert is_in_house("Acme.X", ("Acme.",)) and not is_in_house("Genie.X", ("Acme.",))
