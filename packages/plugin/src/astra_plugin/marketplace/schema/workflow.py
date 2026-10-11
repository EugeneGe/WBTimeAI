"""Workflow 资源 schema（``workflow.yaml``；自含，**不 import 能力包**；W8 裁定 R1）。

字段口径对齐既有工作流生态（入口 / 节点 / 连线 / 输入 / 变量），但本处**自含定义**，
避免 ``plugin → astra_workflow`` 反向依赖。``nodes`` / ``edges`` 为结构保持字段
（``any_list``，逐项深归一并原样往返）。
"""

from __future__ import annotations

from astra_plugin.marketplace.package import KIND_WORKFLOW
from astra_plugin.marketplace.schema import ResourceSchema, SchemaField

__all__ = ["KIND", "MANIFEST_FILE", "FIELDS", "SCHEMA"]

#: 资源种类。
KIND = KIND_WORKFLOW

#: 资源清单文件名。
MANIFEST_FILE = "workflow.yaml"

#: 字段规格（顺序即声明序；``name`` / ``version`` 必填）。
FIELDS: tuple[SchemaField, ...] = (
    SchemaField("name", type="name", required=True),
    SchemaField("version", type="semver", required=True),
    SchemaField("display_name", type="str", default=""),
    SchemaField("description", type="str", default=""),
    SchemaField("entry", type="str", default=""),
    SchemaField("nodes", type="any_list", default=[]),
    SchemaField("edges", type="any_list", default=[]),
    SchemaField("inputs", type="map", default={}),
    SchemaField("variables", type="map", default={}),
)

#: Workflow 资源 schema。
SCHEMA = ResourceSchema(KIND, MANIFEST_FILE, FIELDS)
