from genie_copilot.llm.tokens import TRUNCATION_MARKER, approx_tokens, fit_variables, keep_middle


def test_keep_middle() -> None:
    text = "\n".join(str(i) for i in range(10))
    assert keep_middle(text, 20) == text
    kept = keep_middle(text, 4).splitlines()
    assert kept == [TRUNCATION_MARKER, "3", "4", "5", "6", TRUNCATION_MARKER]


def test_fit_variables_untouched_when_within_budget() -> None:
    values = {"a": "short"}
    assert fit_variables(values, frozenset({"a"}), lambda v: approx_tokens(v["a"]), 100) == values


def test_fit_variables_shrinks_truncatable_only() -> None:
    values = {"fixed": "x" * 40, "log": "\n".join("y" * 39 for _ in range(100))}

    def total(v: dict[str, str]) -> int:  # type: ignore[override]
        return approx_tokens(v["fixed"]) + approx_tokens(v["log"])

    fitted = fit_variables(values, frozenset({"log"}), total, 200)  # type: ignore[arg-type]
    assert fitted is not None
    assert fitted["fixed"] == values["fixed"]
    assert total(fitted) <= 200
    assert TRUNCATION_MARKER in fitted["log"]


def test_fit_variables_gives_up_when_fixed_text_too_big() -> None:
    values = {"fixed": "x" * 4000, "log": "y"}
    assert (
        fit_variables(values, frozenset({"log"}), lambda v: approx_tokens(v["fixed"]), 10) is None
    )
