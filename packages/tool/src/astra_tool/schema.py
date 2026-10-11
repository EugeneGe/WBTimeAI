"""极简 JSON Schema 校验（**零第三方依赖**）。

Astool 抽象包不引入 ``jsonschema`` 等外部依赖，故此处内建一个覆盖常用关键字的
子集校验器，供各 Tool 在执行前校验入参 / 可选校验出参（设计 §2.5.1）。

支持关键字：``type`` / ``enum`` / ``const`` / ``properties`` / ``required`` /
``additionalProperties`` / ``items`` / ``minItems`` / ``maxItems`` / ``minLength`` /
``maxLength`` / ``pattern`` / ``minimum`` / ``maximum`` / ``exclusiveMinimum`` /
``exclusiveMaximum`` / ``anyOf`` / ``oneOf`` / ``allOf`` / ``not``。

校验失败抛 :class:`astra_core.ValidationError`（``VALIDATION_ERROR``）。
"""

from __future__ import annotations

import re
from typing import Any

from astra_core import ValidationError

__all__ = ["validate", "validate_input", "validate_output"]

_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _type_matches(instance: Any, expected: str) -> bool:
    """判断 ``instance`` 是否满足 JSON Schema ``type`` 声明（``bool`` 不算 integer/number）。"""
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "boolean":
        return isinstance(instance, bool)
    types = _TYPE_MAP.get(expected)
    if types is None:
        return True  # 未知类型关键字：不校验
    return isinstance(instance, types)


def _fail(message: str, *, name: str, path: str, **extra: Any) -> None:
    """抛出统一校验错误。"""
    raise ValidationError(
        message,
        data={"schema": name, "path": path, **extra},
    )


def validate(
    instance: Any,
    schema: dict[str, Any] | None,
    *,
    name: str = "value",
    path: str = "$",
) -> None:
    """校验 ``instance`` 是否符合 ``schema``（子集）。

    Args:
        instance: 待校验对象。
        schema: JSON Schema（空 / ``None`` 跳过）。
        name: 校验对象名（用于错误信息）。
        path: 当前 JSON 路径（用于错误定位）。

    Raises:
        ValidationError: 校验失败。
    """
    if not schema:
        return

    expected = schema.get("type")
    if expected is not None:
        candidates = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(instance, item) for item in candidates):
            _fail(
                f"{name} 类型非法（期望 {expected}）",
                name=name,
                path=path,
                expected=expected,
            )

    if "const" in schema and instance != schema["const"]:
        _fail(f"{name} 取值必须为 {schema['const']!r}", name=name, path=path)

    if "enum" in schema and instance not in list(schema["enum"]):
        _fail(f"{name} 取值必须是 {list(schema['enum'])} 之一", name=name, path=path)

    if "anyOf" in schema and not any(
        _is_valid(instance, sub, name=name, path=path) for sub in schema["anyOf"]
    ):
        _fail(f"{name} 不满足 anyOf 任一分支", name=name, path=path)

    if "oneOf" in schema:
        matches = sum(
            1 for sub in schema["oneOf"] if _is_valid(instance, sub, name=name, path=path)
        )
        if matches != 1:
            _fail(f"{name} 须恰好满足 oneOf 一个分支（实际 {matches}）", name=name, path=path)

    if "allOf" in schema and not all(
        _is_valid(instance, sub, name=name, path=path) for sub in schema["allOf"]
    ):
        _fail(f"{name} 不满足 allOf 全部分支", name=name, path=path)

    if "not" in schema and _is_valid(instance, schema["not"], name=name, path=path):
        _fail(f"{name} 命中了 not 禁止的分支", name=name, path=path)

    if isinstance(instance, str):
        _validate_string(instance, schema, name=name, path=path)
    elif isinstance(instance, bool):
        pass
    elif isinstance(instance, (int, float)):
        _validate_number(instance, schema, name=name, path=path)
    elif isinstance(instance, dict):
        _validate_object(instance, schema, name=name, path=path)
    elif isinstance(instance, list):
        _validate_array(instance, schema, name=name, path=path)


def _is_valid(instance: Any, schema: Any, *, name: str, path: str) -> bool:
    """无副作用地判断是否通过某子 schema。"""
    try:
        validate(instance, schema, name=name, path=path)
    except ValidationError:
        return False
    return True


def _validate_string(instance: str, schema: dict[str, Any], *, name: str, path: str) -> None:
    if "minLength" in schema and len(instance) < int(schema["minLength"]):
        _fail(f"{name} 长度小于 {schema['minLength']}", name=name, path=path)
    if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
        _fail(f"{name} 长度大于 {schema['maxLength']}", name=name, path=path)
    pattern = schema.get("pattern")
    if pattern is not None and re.search(pattern, instance) is None:
        _fail(f"{name} 不匹配模式 {pattern!r}", name=name, path=path)


def _validate_number(instance: float, schema: dict[str, Any], *, name: str, path: str) -> None:
    if "minimum" in schema and instance < schema["minimum"]:
        _fail(f"{name} 小于最小值 {schema['minimum']}", name=name, path=path)
    if "maximum" in schema and instance > schema["maximum"]:
        _fail(f"{name} 大于最大值 {schema['maximum']}", name=name, path=path)
    if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
        _fail(f"{name} 须大于 {schema['exclusiveMinimum']}", name=name, path=path)
    if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
        _fail(f"{name} 须小于 {schema['exclusiveMaximum']}", name=name, path=path)


def _validate_object(
    instance: dict[str, Any], schema: dict[str, Any], *, name: str, path: str
) -> None:
    required = schema.get("required") or []
    for key in required:
        if key not in instance:
            _fail(f"{name} 缺少必填字段 {key!r}", name=name, path=f"{path}.{key}", missing=key)

    properties = schema.get("properties") or {}
    for key, value in instance.items():
        child = properties.get(key)
        if child is not None:
            validate(value, child, name=name, path=f"{path}.{key}")
        elif schema.get("additionalProperties") is False:
            _fail(f"{name} 含未声明字段 {key!r}", name=name, path=f"{path}.{key}", field=key)


def _validate_array(instance: list[Any], schema: dict[str, Any], *, name: str, path: str) -> None:
    if "minItems" in schema and len(instance) < int(schema["minItems"]):
        _fail(f"{name} 元素个数小于 {schema['minItems']}", name=name, path=path)
    if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
        _fail(f"{name} 元素个数大于 {schema['maxItems']}", name=name, path=path)
    items = schema.get("items")
    if isinstance(items, dict):
        for index, value in enumerate(instance):
            validate(value, items, name=name, path=f"{path}[{index}]")


def validate_input(schema: dict[str, Any] | None, args: Any, *, name: str = "tool") -> None:
    """校验工具入参（须为对象）。"""
    if not isinstance(args, dict):
        raise ValidationError(
            f"{name} 入参须为对象",
            data={"schema": name, "path": "$"},
        )
    validate(args, schema, name=name, path="$")


def validate_output(schema: dict[str, Any] | None, result: Any, *, name: str = "tool") -> None:
    """校验工具出参（可选）。"""
    validate(result, schema, name=f"{name}.output", path="$")
