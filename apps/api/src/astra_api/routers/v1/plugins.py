"""``/plugins`` 路由（W3 / T2-17；设计 §2.14 / §2.12）。

端点：

- ``GET /plugins``（已装）；``POST /plugins``（安装）；``DELETE /plugins/{id}``（卸载）。

Router **只**依赖 ``AppServices``（N-8）；面向领域 Protocol ``PluginRepository``；
**不** import ORM。
"""

from __future__ import annotations

from typing import Annotated

from astra_core import DomainError, ErrorCode
from fastapi import APIRouter, Depends, Response

from astra_api.dependencies.auth import CurrentUser
from astra_api.dependencies.services import AppServices, get_app_services
from astra_api.schemas.plugin import InstallPluginRequest, PluginResponse

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _to_response(plugin: object) -> PluginResponse:
    """PluginRecord → 响应。"""
    return PluginResponse(
        id=str(getattr(plugin, "id")),  # noqa: B009 - 泛化只读映射
        name=str(getattr(plugin, "name", "")),
        version=str(getattr(plugin, "version", "")),
        kind=str(getattr(plugin, "kind", "")),
        entry_point=getattr(plugin, "entry_point", None),
        permissions=list(getattr(plugin, "permissions", []) or []),
        manifest=dict(getattr(plugin, "manifest", {}) or {}),
        status=str(getattr(plugin, "status", "installed")),
        installed_at=getattr(plugin, "installed_at", None),
    )


@router.get("", response_model=list[PluginResponse], summary="已装插件列表")
def list_plugins(
    user: CurrentUser,  # noqa: ARG001 - 认证依赖（需登录）
    services: Annotated[AppServices, Depends(get_app_services)],
) -> list[PluginResponse]:
    """列出全部已装插件。"""
    return [_to_response(plugin) for plugin in services.plugins.list_all()]


@router.post("", response_model=PluginResponse, status_code=201, summary="安装插件")
def install_plugin(
    payload: InstallPluginRequest,
    user: CurrentUser,  # noqa: ARG001 - 认证依赖（需登录）
    services: Annotated[AppServices, Depends(get_app_services)],
) -> PluginResponse:
    """安装一个插件（``name`` 全局唯一；重复 → ``CONFLICT``）。"""
    from astra_domain import PLUGIN_STATUS_INSTALLED, PluginRecord

    existing = services.plugins.get_by_name(payload.name)
    if existing is not None:
        raise DomainError(
            "插件已安装",
            code=ErrorCode.CONFLICT,
            data={"name": payload.name},
        )
    plugin = services.plugins.add(
        PluginRecord(
            name=payload.name,
            version=payload.version,
            kind=payload.kind,
            entry_point=payload.entry_point,
            permissions=list(payload.permissions),
            manifest=dict(payload.manifest),
            status=PLUGIN_STATUS_INSTALLED,
        )
    )
    return _to_response(plugin)


@router.delete("/{plugin_id}", status_code=204, summary="卸载插件")
def uninstall_plugin(
    plugin_id: str,
    user: CurrentUser,  # noqa: ARG001 - 认证依赖（需登录）
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Response:
    """卸载插件（幂等：不存在不报错）。"""
    services.plugins.delete(plugin_id)
    return Response(status_code=204)
