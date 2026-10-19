import pytest
from pydantic import BaseModel

from genie_copilot.llm.schemas import StrictSchemaError, response_format, strict_json_schema


class Evidence(BaseModel):
    type: str
    ref: str


class Diag(BaseModel):
    category: str
    note: str | None
    evidence: list[Evidence]


class WithDefault(BaseModel):
    category: str = "UNKNOWN"


def test_objects_closed_and_all_required() -> None:
    schema = strict_json_schema(Diag)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["category", "note", "evidence"]
    nested = schema["$defs"]["Evidence"]
    assert nested["additionalProperties"] is False
    assert nested["required"] == ["type", "ref"]


def test_defaults_rejected() -> None:
    with pytest.raises(StrictSchemaError, match="defaults"):
        strict_json_schema(WithDefault)


def test_response_format_wrapper() -> None:
    fmt = response_format(Diag)
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Diag"
    assert fmt["json_schema"]["strict"] is True
