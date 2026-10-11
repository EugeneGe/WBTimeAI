"""Skill 资源 schema（``skill.yaml``；自含，**不 import ``astra_skill``**；W8 裁定 R1）。

字段名**镜像** ``astra_skill.SkillManifest``（name / version / display_name /
description / category / entry / instructions / dependencies / requires / license /
resources / examples / scripts / min_astra_version），但本处**自含定义**，
避免 ``plugin → 能力包`` 反向依赖。
"""

from __future__ import annotations

from astra_plugin.marketplace.package import KIND_SKILL
from astra_plugin.marketplace.schema import ResourceSchema, SchemaField

__all__ = ["KIND", "MANIFEST_FILE", "FIELDS", "SCHEMA", "DEFAULT_INSTRUCTIONS_FILE"]

#: 资源种类。
KIND = KIND_SKILL

#: 资源清单文件名。
MANIFEST_FILE = "skill.yaml"

#: 默认指令文件名（对齐 ``astra_skill``）。
DEFAULT_INSTRUCTIONS_FILE = "instructions.md"

#: 字段规格（顺序即声明序；``name`` / ``version`` 必填）。
FIELDS: tuple[SchemaField, ...] = (
    SchemaField("name", type="name", required=True),
    SchemaField("version", type="semver", required=True),
    SchemaField("display_name", type="str", default=""),
    SchemaField("description", type="str", default=""),
    SchemaField("category", type="str", default=""),
    SchemaField("entry", type="str"),
    SchemaField("instructions", type="str", default=DEFAULT_INSTRUCTIONS_FILE),
    SchemaField("dependencies", type="str_list", default=[]),
    SchemaField("requires", type="str_list", default=[]),
    SchemaField("license", type="str", default=""),
    SchemaField("resources", type="str", default="resources"),
    SchemaField("examples", type="str", default="examples"),
    SchemaField("scripts", type="str", default="scripts"),
    SchemaField("min_astra_version", type="str", default=""),
)

#: Skill 资源 schema。
SCHEMA = ResourceSchema(KIND, MANIFEST_FILE, FIELDS)
