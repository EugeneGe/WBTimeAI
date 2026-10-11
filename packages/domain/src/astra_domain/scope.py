"""查询范围过滤契约 ``ScopeFilter``（Phase 2 · W7 / T2-40）。

设计依据：设计 §2.15.4（A-7）「所有 Repository 接收
``ScopeFilter(tenant_id, organization_id?, workspace_id?)``」；**W7 开工前架构裁定** §6.1。

约定：

- ``tenant_id`` **必填**——承载租户**硬隔离**（总纲 I-1 / I-2），组织 / 工作区过滤**叠加**
  其上，**不替代**；
- ``organization_id`` / ``workspace_id`` **可选**——缺省（``None``）**不额外过滤**；
  ``organization_id`` 的**硬隔离**由 **Phase 3a** 启用（本波仅提供契约，见 R13）；
- 🔴 **零框架依赖**：仅依赖标准库 ``dataclasses``（受
  ``tests/integration/test_layering.py::test_domain_has_no_framework_dependencies`` 覆盖），
  不引入 ``fastapi`` / ``starlette`` / ``sqlalchemy`` / ``alembic`` / ``pydantic`` / ``sqlmodel``。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ScopeFilter"]


@dataclass(frozen=True)
class ScopeFilter:
    """仓储查询范围过滤（租户硬隔离 + 可选组织 / 工作区维度）。

    Attributes:
        tenant_id: 租户标识（**必填**；硬隔离，I-1/I-2）。
        organization_id: 组织标识（可选；``None`` ＝ 不做组织过滤）。
        workspace_id: 工作区标识（可选；``None`` ＝ 不做工作区过滤）。

    Examples:
        >>> ScopeFilter(tenant_id="t1")
        ScopeFilter(tenant_id='t1', organization_id=None, workspace_id=None)
        >>> ScopeFilter(tenant_id="t1", organization_id="o1")
        ScopeFilter(tenant_id='t1', organization_id='o1', workspace_id=None)
    """

    tenant_id: str
    organization_id: str | None = None
    workspace_id: str | None = None
