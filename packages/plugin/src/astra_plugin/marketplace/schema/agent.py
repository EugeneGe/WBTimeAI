"""Agent 资源 schema（``agent.yaml``；自含，**不 import 能力包**；W8 裁定 R1）。

字段口径对齐既有 Agent 生态（模型 / 指令 / 工具 / 技能 / 知识 / 记忆 / 权限），
但本处**自含定义**，避免 ``plugin → astra_agent`` 反向依赖。
"""

from __future__ import annotations

from astra_plugin.marketplace.package import KIND_AGENT
from astra_plugin.marketplace.schema import ResourceSchema, SchemaField

__all__ = ["KIND", "MANIFEST_FILE", "FIELDS", "SCHEMA"]

#: 资源种类。
KIND = KIND_AGENT

#: 资源清单文件名。
MANIFEST_FILE = "agent.yaml"

#: 字段规格（顺序即声明序；``name`` / ``version`` 必填）。
FIELDS: tuple[SchemaField, ...] = (
    SchemaField("name", type="name", required=True),
    SchemaField("version", type="semver", required=True),
    SchemaField("display_name", type="str", default=""),
    SchemaField("description", type="str", default=""),
    SchemaField("model", type="str", default=""),
    SchemaField("system_prompt", type="str", default=""),
    SchemaField("tools", type="str_list", default=[]),
    SchemaField("skills", type="str_list", default=[]),
    SchemaField("knowledge", type="str_list", default=[]),
    SchemaField("memory", type="bool", default=False),
    SchemaField("permissions", type="str_list", default=[]),
)

#: Agent 资源 schema。
SCHEMA = ResourceSchema(KIND, MANIFEST_FILE, FIELDS)
