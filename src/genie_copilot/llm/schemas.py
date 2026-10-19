"""JSON-schema export for strict structured output.

Strict mode needs every object closed (`additionalProperties: false`), every property
required and no defaults. Models with defaults are rejected so the author notices.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StrictSchemaError(ValueError):
    pass


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    _close(schema, path=model.__name__)
    return schema


def response_format(model: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "schema": strict_json_schema(model),
            "strict": True,
        },
    }


def _close(node: Any, path: str) -> None:
    if isinstance(node, dict):
        if "default" in node:
            raise StrictSchemaError(f"{path}: defaults are not allowed in strict schemas")
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for key, value in node.items():
            _close(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _close(item, f"{path}[{i}]")
