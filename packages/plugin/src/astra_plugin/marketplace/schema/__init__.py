"""Marketplace 资源 schema 引擎（自含，**不 import 能力包**；W8 裁定 R1 / §3.1）。

三类资源（``agent`` / ``skill`` / ``workflow``）各自 schema 落
``schema/{agent,skill,workflow}.py``，字段口径**镜像** ``astra_skill.SkillManifest``
等既有清单，但**本处自含定义**，避免 ``plugin → 能力包`` 反向依赖（R1）。

- :class:`SchemaField`：字段规格（名 / 类型 / 是否必填 / 默认值）；
- :class:`ResourceSchema`：字段校验 + **规范化**（保留未知字段，保证**无损往返**）；
- :func:`get_schema` / :func:`normalize_resource` / :func:`validate_resource`。

🔴 零 Web / ORM：仅依赖标准库 + ``astra_core`` + 同子包 :mod:`.package`（常量）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from astra_core import DomainError, ErrorCode

from astra_plugin.marketplace.package import (
    KIND_AGENT,
    KIND_SKILL,
    KIND_WORKFLOW,
    NAME_PATTERN,
    VALID_KINDS,
    VERSION_PATTERN,
)

__all__ = [
    "KIND_AGENT",
    "KIND_SKILL",
    "KIND_WORKFLOW",
    "VALID_KINDS",
    "SchemaField",
    "ResourceSchema",
    "SCHEMAS",
    "KIND_MANIFEST_FILES",
    "get_schema",
    "normalize_resource",
    "validate_resource",
]

#: 允许的字段类型。
_FIELD_TYPES: frozenset[str] = frozenset(
    {"str", "name", "semver", "bool", "int", "str_list", "any", "any_list", "map"}
)


def _validation_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``VALIDATION_ERROR``。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def _deep_normalize(value: Any) -> Any:
    """把任意 JSON-ish 值归一为**纯 dict / list / 标量**（确定性往返用）。"""
    if isinstance(value, Mapping):
        return {str(key): _deep_normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_normalize(item) for item in value]
    return value


def _validate_scalar_str(value: Any, *, field: str) -> str:
    """把标量归一为字符串（仅接受 str / 数值）。"""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    raise _validation_error("字段须为字符串", field=field)


@dataclass(frozen=True)
class SchemaField:
    """资源 schema 的单个字段规格。

    Attributes:
        name: 字段名。
        type: 字段类型（``str`` / ``name`` / ``semver`` / ``bool`` / ``int`` /
            ``str_list`` / ``any`` / ``any_list`` / ``map``）。
        required: 是否必填。
        default: 缺省值（``None`` 且非必填 → 规范化时**省略**）。
    """

    name: str
    type: str = "str"
    required: bool = False
    default: Any = None


class ResourceSchema:
    """单类资源的字段校验 + 规范化（无损往返）。"""

    def __init__(self, kind: str, manifest_file: str, fields: Sequence[SchemaField]) -> None:
        """构造。

        Args:
            kind: 资源种类（须在 ``VALID_KINDS`` 内）。
            manifest_file: 资源清单文件名（如 ``agent.yaml``）。
            fields: 字段规格序列。
        """
        if kind not in VALID_KINDS:
            raise _validation_error("资源 schema kind 非法", kind=kind)
        self.kind = kind
        self.manifest_file = manifest_file
        self._fields: dict[str, SchemaField] = {}
        for spec in fields:
            if spec.type not in _FIELD_TYPES:
                raise _validation_error("schema 字段类型非法", field=spec.name, type=spec.type)
            self._fields[spec.name] = spec

    @property
    def fields(self) -> tuple[SchemaField, ...]:
        """字段规格（按声明序）。"""
        return tuple(self._fields.values())

    @property
    def required_fields(self) -> tuple[str, ...]:
        """必填字段名。"""
        return tuple(spec.name for spec in self._fields.values() if spec.required)

    @property
    def known_fields(self) -> tuple[str, ...]:
        """已知字段名。"""
        return tuple(self._fields)

    def _coerce(self, spec: SchemaField, value: Any) -> Any:
        """把字段值按类型归一（非法 → ``VALIDATION_ERROR``）。"""
        field = spec.name
        if spec.type == "str":
            return _validate_scalar_str(value, field=field)
        if spec.type == "name":
            text = _validate_scalar_str(value, field=field)
            if not NAME_PATTERN.match(text):
                raise _validation_error("name 非法", field=field, value=text)
            return text
        if spec.type == "semver":
            text = _validate_scalar_str(value, field=field)
            if not VERSION_PATTERN.match(text):
                raise _validation_error("version 非语义化版本", field=field, value=text)
            return text
        if spec.type == "bool":
            if not isinstance(value, bool):
                raise _validation_error("字段须为布尔", field=field, value=value)
            return value
        if spec.type == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise _validation_error("字段须为整数", field=field, value=value)
            return value
        if spec.type == "str_list":
            if value is None:
                return []
            if isinstance(value, str):
                return [value]
            if isinstance(value, (list, tuple)):
                return [str(item) for item in value]
            raise _validation_error("字段须为字符串列表", field=field)
        if spec.type == "any_list":
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return [_deep_normalize(item) for item in value]
            raise _validation_error("字段须为列表", field=field)
        if spec.type == "map":
            if value is None:
                return {}
            if isinstance(value, Mapping):
                return {str(key): _deep_normalize(item) for key, item in value.items()}
            raise _validation_error("字段须为映射", field=field)
        # spec.type == "any"
        return _deep_normalize(value)

    def normalize(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """校验并规范化资源字典（**无损**：未知字段原样保留）。

        Args:
            data: 资源清单（YAML 解析后的映射）。

        Returns:
            规范化字典：已知字段按类型归一；缺省非必填字段按 ``default`` 补齐或省略；
            未知字段深归一后保留。

        Raises:
            DomainError: 顶层非映射 / 缺必填字段 / 字段类型非法（``VALIDATION_ERROR``）。
        """
        if not isinstance(data, Mapping):
            raise _validation_error(f"{self.kind}.yaml 顶层须为映射", kind=self.kind)
        normalized: dict[str, Any] = {}
        for spec in self._fields.values():
            if spec.name in data:
                value = data[spec.name]
                if value is None:
                    # 显式 ``null`` 属**契约内输入**，归一到与「缺席」**同一**规范形：
                    # 有非 None 默认 → 物化默认；默认 None → 省略该键。如此
                    # ``normalize`` 幂等（``normalize(normalize(x)) == normalize(x)``），
                    # 且 ``export→import→export`` 规范化后 ``diff == 空``（I-P2-18 / D13）。
                    if spec.required:
                        raise _validation_error(
                            f"{self.kind}.yaml: 必填字段不可为空", field=spec.name, kind=self.kind
                        )
                    if spec.default is not None:
                        normalized[spec.name] = _deep_normalize(spec.default)
                    # default is None → 省略该键（缺席即规范形）
                    continue
                normalized[spec.name] = self._coerce(spec, value)
            elif spec.required:
                raise _validation_error(
                    f"{self.kind}.yaml: 缺少必填字段", field=spec.name, kind=self.kind
                )
            elif spec.default is not None:
                normalized[spec.name] = _deep_normalize(spec.default)
        for key, value in data.items():
            name = str(key)
            if name not in self._fields:
                normalized[name] = _deep_normalize(value)
        return normalized

    def validate(self, data: Mapping[str, Any]) -> None:
        """校验资源字典（不返回规范化结果）。

        Raises:
            DomainError: 校验失败（``VALIDATION_ERROR``）。
        """
        self.normalize(data)


#: 资源种类 → 资源清单文件名（由子模块 SCHEMA 汇总）。
KIND_MANIFEST_FILES: dict[str, str] = {}

#: 资源种类 → :class:`ResourceSchema`。
SCHEMAS: dict[str, ResourceSchema] = {}


def _register() -> None:
    """汇总三个资源 schema 子模块的 ``SCHEMA`` 到模块级注册表。"""
    from astra_plugin.marketplace.schema import agent, skill, workflow

    for module in (agent, skill, workflow):
        schema: ResourceSchema = module.SCHEMA
        SCHEMAS[schema.kind] = schema
        KIND_MANIFEST_FILES[schema.kind] = schema.manifest_file


def get_schema(kind: str) -> ResourceSchema:
    """返回某资源种类的 :class:`ResourceSchema`。

    Raises:
        DomainError: 种类非法（``VALIDATION_ERROR``）。
    """
    if kind not in SCHEMAS:
        raise _validation_error("未知资源种类", kind=kind)
    return SCHEMAS[kind]


def normalize_resource(kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """按种类规范化资源字典（R7 前置：三类资源统一入口）。"""
    return get_schema(kind).normalize(data)


def validate_resource(kind: str, data: Mapping[str, Any]) -> None:
    """按种类校验资源字典。"""
    get_schema(kind).validate(data)


_register()
