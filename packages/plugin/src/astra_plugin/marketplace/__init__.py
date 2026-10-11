"""``astra_plugin.marketplace``——Marketplace 包格式与导入导出子包（W8 / T2-42）。

落在 ``plugin``（**抽象包**）内，资源 schema **自含**，**不 import 任何能力包**
（W8 裁定 R1）。分层冻结：本子包仅可 import
``{标准库, pyyaml, astra_core, astra_domain}``；禁 ``{fastapi, starlette, sqlalchemy,
alembic, astra_database, astra_security, astra_application, astra_agent, astra_skill,
astra_workflow, astra_config}``。

子模块：

- :mod:`~astra_plugin.marketplace.serialize`：确定性序列化（R7 唯一出口）；
- :mod:`~astra_plugin.marketplace.package`：``astra-package.yaml`` 清单；
- :mod:`~astra_plugin.marketplace.schema`：三类资源 schema（自含）；
- :mod:`~astra_plugin.marketplace.import_`：导入（schema + 依赖 + 敏感校验）；
- :mod:`~astra_plugin.marketplace.export`：导出（确定性序列化）；
- :mod:`~astra_plugin.marketplace.publish` / :mod:`~astra_plugin.marketplace.index`：
  发布与静态注册表（T2-43）。
"""

from __future__ import annotations

from astra_plugin.marketplace.export import (
    build_manifest,
    export_manifest_text,
    export_package,
    export_resource_text,
)
from astra_plugin.marketplace.import_ import (
    ImportedPackage,
    PackageInspection,
    content_digest,
    import_package,
    inspect,
    inspect_manifest,
    load_package,
    load_resource,
    scan_sensitive,
    validate,
    validate_dependencies,
)
from astra_plugin.marketplace.index import (
    INDEX_FILE_NAME,
    SCHEMA_VERSION,
    IndexEntry,
    RegistryIndex,
    RegistryIndexData,
)
from astra_plugin.marketplace.package import (
    DEFAULT_CORE_VERSION,
    KIND_AGENT,
    KIND_SKILL,
    KIND_WORKFLOW,
    PACKAGE_MANIFEST_FILE,
    VALID_KINDS,
    AstraPackageManifest,
    compute_sha256,
    load_manifest,
    manifest_from_dict,
    manifest_to_dict,
    parse_manifest,
    satisfies_core_compat,
    version_key,
)
from astra_plugin.marketplace.publish import (
    PublishSummary,
    build_archive,
    publish_package,
)
from astra_plugin.marketplace.schema import (
    KIND_MANIFEST_FILES,
    normalize_resource,
    validate_resource,
)
from astra_plugin.marketplace.serialize import (
    atomic_write_bytes,
    canonical_dump,
    load,
    normalize,
    write_canonical,
)

__all__ = [
    # 序列化（R7）
    "canonical_dump",
    "load",
    "normalize",
    "write_canonical",
    "atomic_write_bytes",
    # 清单
    "PACKAGE_MANIFEST_FILE",
    "KIND_AGENT",
    "KIND_SKILL",
    "KIND_WORKFLOW",
    "VALID_KINDS",
    "KIND_MANIFEST_FILES",
    "normalize_resource",
    "validate_resource",
    "DEFAULT_CORE_VERSION",
    "AstraPackageManifest",
    "version_key",
    "satisfies_core_compat",
    "manifest_from_dict",
    "manifest_to_dict",
    "parse_manifest",
    "load_manifest",
    "compute_sha256",
    # 导入
    "ImportedPackage",
    "PackageInspection",
    "scan_sensitive",
    "validate_dependencies",
    "validate",
    "inspect",
    "inspect_manifest",
    "load_resource",
    "content_digest",
    "import_package",
    "load_package",
    # 导出
    "export_package",
    "export_resource_text",
    "export_manifest_text",
    "build_manifest",
    # 注册表 / 发布（T2-43）
    "INDEX_FILE_NAME",
    "SCHEMA_VERSION",
    "IndexEntry",
    "RegistryIndex",
    "RegistryIndexData",
    "PublishSummary",
    "build_archive",
    "publish_package",
]
