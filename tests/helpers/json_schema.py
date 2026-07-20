"""Tiny standard-library evaluator for the checked-in schema's deterministic corpus."""

from __future__ import annotations

from typing import Any


class SchemaReject(ValueError):
    pass


def validate_schema(instance: Any, schema: dict[str, Any]) -> None:
    _validate(instance, schema, schema)


def _validate(instance: Any, node: dict[str, Any], root: dict[str, Any]) -> None:
    if "$ref" in node:
        target: Any = root
        for token in node["$ref"].removeprefix("#/ ").replace("#/", "").split("/"):
            if token:
                target = target[token]
        _validate(instance, target, root)
        return
    if "oneOf" in node:
        accepted = 0
        for option in node["oneOf"]:
            try:
                _validate(instance, option, root)
                accepted += 1
            except SchemaReject:
                pass
        if accepted != 1:
            raise SchemaReject("oneOf")
    if "const" in node and instance != node["const"]:
        raise SchemaReject("const")
    if "enum" in node and instance not in node["enum"]:
        raise SchemaReject("enum")
    if "type" in node:
        allowed = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_matches_type(instance, expected) for expected in allowed):
            raise SchemaReject("type")
    if isinstance(instance, dict):
        required = set(node.get("required", ()))
        if not required.issubset(instance):
            raise SchemaReject("required")
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False and not set(instance).issubset(properties):
            raise SchemaReject("additionalProperties")
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], root)
        _validate_total_utf8_bytes(instance, node)
    elif isinstance(instance, list):
        if "maxItems" in node and len(instance) > node["maxItems"]:
            raise SchemaReject("maxItems")
        if "items" in node:
            for item in instance:
                _validate(item, node["items"], root)
    elif isinstance(instance, str):
        if "minLength" in node and len(instance) < node["minLength"]:
            raise SchemaReject("minLength")
        if "maxLength" in node and len(instance) > node["maxLength"]:
            raise SchemaReject("maxLength")
    elif type(instance) is int:
        if "minimum" in node and instance < node["minimum"]:
            raise SchemaReject("minimum")


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "number": type(value) in {int, float},
    }.get(expected, False)


def _validate_total_utf8_bytes(instance: dict[str, Any], node: dict[str, Any]) -> None:
    """Evaluate the repository's aggregate UTF-8 byte-budget schema extension."""

    extension = node.get("x-portable-resume-max-total-utf8-bytes")
    if extension is None:
        return
    if not isinstance(extension, dict):
        raise SchemaReject("x-portable-resume-max-total-utf8-bytes")
    limit = extension.get("limit")
    string_fields = extension.get("stringFields")
    array_field = extension.get("arrayField")
    array_string_field = extension.get("arrayStringField")
    if (
        type(limit) is not int
        or limit < 0
        or not isinstance(string_fields, list)
        or not all(isinstance(field, str) for field in string_fields)
        or not isinstance(array_field, str)
        or not isinstance(array_string_field, str)
    ):
        raise SchemaReject("x-portable-resume-max-total-utf8-bytes")

    total = sum(
        len(value.encode("utf-8"))
        for field in string_fields
        if isinstance((value := instance.get(field)), str)
    )
    values = instance.get(array_field, ())
    if isinstance(values, list):
        total += sum(
            len(value.encode("utf-8"))
            for item in values
            if isinstance(item, dict) and isinstance((value := item.get(array_string_field)), str)
        )
    if total > limit:
        raise SchemaReject("x-portable-resume-max-total-utf8-bytes")
