"""``MarketplaceService``——Marketplace 用例编排器（W8 / T2-44；设计 §2.12 / §2.13.1 / 裁定 R4）。

**应用/用例层（第三类）**：编排「安装前预检 / 导入 / 导出」，**不**承载实体持久化、
**不**提供被 Runtime 消费的 Protocol、**零** Web / ORM（``test_application_import_boundary``）。

- :meth:`preview`：解析包 → 清单 schema + ``core_compat`` 校验 + 敏感扫描 → 元数据（**不落库**）；
- :meth:`import_package`：schema / 依赖 / 敏感校验 + ``expected_sha256`` 校验 + ``can()`` 权限 +
  **同名同版本异摘要拒绝** → 经**注入**的 :class:`ResourceImporter` 创建资源（落库）；
- :meth:`export_resource`：经注入的 :class:`ResourceImporter` 读资源 → 规范化 yaml（**可往返**）。

🔴 依赖 ``astra_plugin.marketplace``（**新边 application→plugin**，R4；无环——``plugin`` 禁 import
   ``astra_application``）。资源创建 / 读取经**注入 Protocol**（:class:`ResourceImporter`），
   保持对具体能力包（agent / skill / workflow）**松耦合**。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from astra_core import DomainError, ErrorCode, PermissionDeniedError
from astra_plugin.marketplace import (
    DEFAULT_CORE_VERSION,
    KIND_MANIFEST_FILES,
    build_manifest,
    canonical_dump,
    content_digest,
    load,
    manifest_from_dict,
    manifest_to_dict,
    normalize_resource,
    scan_sensitive,
    validate,
    validate_dependencies,
)

from ..dto.marketplace import (
    IMPORT_STATUS_IMPORTED,
    IMPORT_STATUS_PREVIEW,
    ExportResultDTO,
    ImportResultDTO,
    PackageMetadataDTO,
)
from .base import ApplicationService

__all__ = [
    "RESOURCE_KEY",
    "ACTION_IMPORT",
    "ACTION_EXPORT",
    "ResourceImporter",
    "MarketplacePermissionChecker",
    "MarketplaceService",
]

#: 包文档中承载资源清单的键（``astra-package.yaml`` 清单字段 + ``resource``）。
RESOURCE_KEY = "resource"

#: 权限动作码（供组合根经 ``identity.authorization.has_permission`` 判定）。
ACTION_IMPORT = "marketplace:import"
ACTION_EXPORT = "marketplace:export"


@runtime_checkable
class MarketplacePermissionChecker(Protocol):
    """Marketplace 权限判定（组合根注入；结构化满足即可）。"""

    def can(self, user_id: str, permission: str) -> bool:
        """判定用户是否具备某权限码。"""
        ...


@runtime_checkable
class ResourceImporter(Protocol):
    """资源创建 / 读取端口（组合根注入；适配既有 agent / skill / workflow 用例）。"""

    def existing_digest(self, *, kind: str, name: str, version: str, tenant_id: str) -> str | None:
        """返回同 ``(kind, name, version)`` 已存在资源的**内容摘要**（无 → ``None``）。"""
        ...

    def create(
        self,
        *,
        kind: str,
        manifest: Mapping[str, Any],
        resource: Mapping[str, Any],
        tenant_id: str,
        owner_id: str,
    ) -> str:
        """创建资源（返回资源 id）。"""
        ...

    def read(self, *, kind: str, resource_id: str, tenant_id: str) -> Mapping[str, Any] | None:
        """读取资源清单（无 / 跨租户 → ``None``）。"""
        ...


class MarketplaceService(ApplicationService):
    """Marketplace 用例编排器（DI 注入 importer + 可选权限判定；零 ORM）。"""

    importer: ResourceImporter
    permission: MarketplacePermissionChecker | None
    core_version: str

    def __init__(
        self,
        *,
        importer: ResourceImporter,
        permission: MarketplacePermissionChecker | None = None,
        core_version: str = DEFAULT_CORE_VERSION,
    ) -> None:
        """装配用例编排器（依赖由**组合根**注入）。

        Args:
            importer: 资源创建 / 读取端口（注入 Protocol）。
            permission: 权限判定（可选；``None`` → 不额外校验，权限由 Router 守卫兜底）。
            core_version: 当前 core 版本（``core_compat`` 校验）。
        """
        super().__init__(importer=importer, permission=permission, core_version=core_version)

    # -- 预检（安装前展示；不落库） ------------------------------------------

    def preview(
        self,
        package_yaml: str,
        *,
        user_id: str,
        core_version: str | None = None,
    ) -> PackageMetadataDTO:
        """解析包并返回安装前元数据（**不落库**）。

        Raises:
            DomainError: YAML / 清单 schema 非法、``core_compat`` 越界或敏感命中
                （``VALIDATION_ERROR``）；权限不足（``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_IMPORT)
        manifest, _resource = self._parse_package(package_yaml)
        validate(manifest, core_version=core_version or self.core_version)
        validate_dependencies(manifest.dependencies)
        scan_sensitive(manifest_to_dict(manifest))
        return self._metadata(manifest)

    # -- 导入（执行；落库） --------------------------------------------------

    def import_package(
        self,
        package_yaml: str,
        *,
        user_id: str,
        tenant_id: str,
        expected_sha256: str | None = None,
        core_version: str | None = None,
    ) -> ImportResultDTO:
        """校验并导入包（经注入 :class:`ResourceImporter` 创建资源）。

        Args:
            package_yaml: 包文档 yaml（清单字段 + ``resource``）。
            user_id / tenant_id: 主体与租户标识。
            expected_sha256: 期望内容摘要（不匹配 → ``VALIDATION_ERROR``）。
            core_version: 当前 core 版本（覆盖默认）。

        Returns:
            :class:`ImportResultDTO`（``status=IMPORTED``）。

        Raises:
            DomainError: 校验失败 / ``expected_sha256`` 不匹配（``VALIDATION_ERROR``）；
                权限不足（``PERMISSION_DENIED``）；同名同版本异摘要（``CONFLICT``）。
        """
        core = core_version or self.core_version
        manifest, resource = self._parse_package(package_yaml)
        validate(manifest, core_version=core)
        validate_dependencies(manifest.dependencies)
        scan_sensitive(manifest_to_dict(manifest))
        if resource is None:
            raise DomainError(
                "导入包缺少资源内容（resource）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"kind": manifest.kind, "name": manifest.name, "version": manifest.version},
            )
        normalized = normalize_resource(manifest.kind, resource)
        scan_sensitive(normalized)
        digest = content_digest(normalized)
        if expected_sha256 and expected_sha256 != digest:
            raise DomainError(
                "SHA-256 校验失败（与 expected_sha256 不一致）",
                code=ErrorCode.VALIDATION_ERROR,
                data={"expected_sha256": expected_sha256, "actual_sha256": digest},
            )
        self._require(user_id, ACTION_IMPORT)
        existing = self.importer.existing_digest(
            kind=manifest.kind,
            name=manifest.name,
            version=manifest.version,
            tenant_id=tenant_id,
        )
        if existing is not None and existing != digest:
            raise DomainError(
                "同名同版本内容摘要不同，拒绝导入",
                code=ErrorCode.CONFLICT,
                data={
                    "kind": manifest.kind,
                    "name": manifest.name,
                    "version": manifest.version,
                },
            )
        if existing is None:
            self.importer.create(
                kind=manifest.kind,
                manifest=manifest,
                resource=normalized,
                tenant_id=tenant_id,
                owner_id=user_id,
            )
        return ImportResultDTO(
            status=IMPORT_STATUS_IMPORTED,
            kind=manifest.kind,
            name=manifest.name,
            version=manifest.version,
            digest=digest,
        )

    # -- 导出（规范化 yaml，可往返） ----------------------------------------

    def export_resource(
        self,
        *,
        kind: str,
        resource_id: str,
        user_id: str,
        tenant_id: str,
    ) -> ExportResultDTO:
        """把已落地资源导出为**规范化 yaml 全文**（可再次导入；往返等价）。

        Raises:
            DomainError: 资源种类非法（``VALIDATION_ERROR``）；资源不存在 / 跨租户
                （``NOT_FOUND``）；权限不足（``PERMISSION_DENIED``）。
        """
        self._require(user_id, ACTION_EXPORT)
        if kind not in KIND_MANIFEST_FILES:
            raise DomainError("未知资源种类", code=ErrorCode.VALIDATION_ERROR, data={"kind": kind})
        resource = self.importer.read(kind=kind, resource_id=resource_id, tenant_id=tenant_id)
        if resource is None:
            raise DomainError(
                "资源不存在",
                code=ErrorCode.NOT_FOUND,
                data={"kind": kind, "id": resource_id},
            )
        normalized = normalize_resource(kind, resource)
        digest = content_digest(normalized)
        manifest = build_manifest(
            kind=kind,
            name=str(normalized.get("name") or ""),
            version=str(normalized.get("version") or ""),
            manifest_path=KIND_MANIFEST_FILES[kind],
            core_compat=f">={self.core_version}",
            artifact_sha256=digest,
        )
        bundle = manifest_to_dict(manifest)
        bundle[RESOURCE_KEY] = normalized
        return ExportResultDTO(
            yaml=canonical_dump(bundle),
            kind=kind,
            id=resource_id,
            digest=digest,
        )

    # -- 内部 ----------------------------------------------------------------

    def _parse_package(self, package_yaml: str) -> tuple[Any, Mapping[str, Any] | None]:
        """解析包文档 yaml 为 ``(manifest, resource)``。

        Raises:
            DomainError: 顶层非映射或清单非法（``VALIDATION_ERROR``）。
        """
        data = load(package_yaml)
        if not isinstance(data, Mapping):
            raise DomainError(
                "包 YAML 顶层须为映射", code=ErrorCode.VALIDATION_ERROR, data={"field": "package"}
            )
        payload = dict(data)
        resource = payload.pop(RESOURCE_KEY, None)
        kind = str(payload.get("kind") or "")
        if not payload.get("manifest_path") and kind in KIND_MANIFEST_FILES:
            payload["manifest_path"] = KIND_MANIFEST_FILES[kind]
        manifest = manifest_from_dict(payload)
        if resource is not None and not isinstance(resource, Mapping):
            raise DomainError(
                "resource 须为映射", code=ErrorCode.VALIDATION_ERROR, data={"field": "resource"}
            )
        return manifest, resource

    @staticmethod
    def _metadata(manifest: Any) -> PackageMetadataDTO:
        """清单 → 安装前元数据 DTO。"""
        return PackageMetadataDTO(
            status=IMPORT_STATUS_PREVIEW,
            kind=manifest.kind,
            name=manifest.name,
            version=manifest.version,
            core_compat=manifest.core_compat,
            author=manifest.author,
            license=manifest.license,
            dependencies=list(manifest.dependencies),
            manifest_path=manifest.manifest_path,
            artifact_sha256=manifest.artifact_sha256,
            signature_present=manifest.signature_present,
        )

    def _require(self, user_id: str, action: str) -> None:
        """权限守卫（未注入判定器 → 放行，权限由 Router 依赖兜底）。

        Raises:
            PermissionDeniedError: 判定器存在且拒绝（``PERMISSION_DENIED``）。
        """
        if self.permission is None:
            return
        if not self.permission.can(user_id, action):
            raise PermissionDeniedError(f"缺少权限：{action}", data={"permission": action})
