import re

import pytest

from genie_copilot.logs.masking import PLACEHOLDER, Masker, MaskRules, mask
from genie_copilot.logs.parser import parse

from .conftest import IN_HOUSE, PLANTED, RULES, load, log_names

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ACCOUNT = re.compile(r"(?<![\w.-])\d{8,20}(?![\w-])")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("mail jane.roe@corp.example.com now", "EMAIL"),
        (r"C:\Users\jroe\Desktop\a.txt", "USER"),
        ("IBAN DE89370400440532013000 used", "IBAN"),
        ("ISIN US0378331005 used", "ISIN"),
        ("card 4111 1111 1111 1111 used", "CARD"),
        ("account 004512345678 used", "ACCOUNT"),
        ("host 192.168.1.10 down", "IP"),
    ],
)
def test_patterns(text: str, kind: str) -> None:
    out = mask(text)
    assert re.search(rf"<{kind}_1>", out), out


def test_names_and_host_rules() -> None:
    rules = MaskRules(names=("Jane Roe",), host_patterns=(r"\bVDI-[\w-]+\b",))
    out = mask("jane roe logged in on VDI-LON-0042", rules)
    assert out == "<NAME_1> logged in on <HOST_1>"


def test_extra_terms_whole_word_only() -> None:
    out = mask("user bob ran bobcat with bob.", extra_terms=["bob", None, "x"])
    assert out == "user <ID_1> ran bobcat with <ID_1>."


def test_same_value_same_placeholder_and_reverse_map() -> None:
    masker = Masker()
    a = masker.mask("a@x.com b@x.com")
    b = masker.mask("again A@X.com")
    assert a == "<EMAIL_1> <EMAIL_2>" and b == "again <EMAIL_1>"
    assert masker.mapping == {"<EMAIL_1>": "a@x.com", "<EMAIL_2>": "b@x.com"}


def test_numbers_that_are_not_accounts_survive() -> None:
    text = "line 42 took 30000 ms, guid 7f3c2a1e-9b8d-4c6e-a1f2-3d4e5f6a7b8c, v1.2.3.4567"
    assert mask(text) == text


@pytest.mark.parametrize("name", log_names())
def test_masking_is_idempotent(name: str) -> None:
    text = "\n".join(load(name).lines)
    once = mask(text, RULES, ["jdoe"])
    assert mask(once, RULES, ["jdoe"]) == once


@pytest.mark.parametrize("name", log_names())
def test_no_planted_value_survives_parsing(name: str) -> None:
    raw = load(name)
    masker = Masker(RULES, extra_terms=["jdoe", "asmith", "cmorgan"])
    parsed = parse(raw, masker, IN_HOUSE)
    if parsed is None:
        return
    dumped = parsed.model_dump_json()
    for value in PLANTED:
        assert value.lower() not in dumped.lower(), value
    for text in [parsed.message, *(w.text for w in parsed.window)]:
        assert not EMAIL.search(PLACEHOLDER.sub("", text))
        assert not ACCOUNT.search(text)
