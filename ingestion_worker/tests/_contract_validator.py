"""Dependency-free JSON-Schema checker (worker's own copy — the worker is decoupled).

Mirror of the core-api side. Supports the subset the contracts use: type, required,
properties, items, enum, minimum, maximum. additionalProperties:true is honoured by not
flagging unknown keys.
"""

from __future__ import annotations

from typing import Any

_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    _check(instance, schema, path, errors)
    return errors


def _check(instance: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected = schema.get("type")
    if expected is not None:
        py = _JSON_TYPES.get(expected)
        if expected in ("number", "integer") and isinstance(instance, bool):
            errors.append(f"{path}: expected {expected}, got boolean")
            return
        if py is not None and not isinstance(instance, py):
            errors.append(f"{path}: expected {expected}, got {type(instance).__name__}")
            return

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")
        for key, subschema in schema.get("properties", {}).items():
            if key in instance:
                _check(instance[key], subschema, f"{path}.{key}", errors)

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            _check(item, schema["items"], f"{path}[{i}]", errors)
