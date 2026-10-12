"""Project / Workspace-Files / Environment schema（W10 / T2-49；设计 §2.8 / §2.12）。

面向 ``/projects`` 与 ``/workspaces/{id}/files|environment`` 的请求 / 响应模型。

🔴 环境变量 ``env_vars`` **敏感项只读引用**（W10 裁定 R-W10-02）：明文**禁止回显**——
   非敏感项返回明文标量（``masked=False``），敏感项仅返回引用串（``ref``：
   ``credential:<id>`` / ``secret:<NAME>``）并置 ``masked=True``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "CreateProjectRequest",
    "ProjectResponse",
    "FileObjectResponse",
    "FileContentResponse",
    "EnvironmentVarResponse",
    "EnvironmentResponse",
    # R3 / T2-60：远程 Project 视图
    "CloneProjectRequest",
    "CloneProjectResponse",
    "ProjectStatusResponse",
    "GitRefResponse",
]


class CreateProjectRequest(BaseModel):
    """创建项目请求（``name`` + ``workspace_id`` 必填）。"""

    name: str = Field(min_length=1, max_length=255, description="项目名称")
    workspace_id: str = Field(min_length=1, description="归属 Workspace 标识")
    description: str | None = Field(default=None, description="项目描述")
    repo_url: str | None = Field(default=None, description="仓库地址（禁含用户名 / Token / 密码）")
    default_branch: str | None = Field(default=None, description="默认分支")
    organization_id: str | None = Field(default=None, description="组织归属（可空）")
    settings: dict[str, Any] = Field(default_factory=dict, description="项目设置（JSON）")


class ProjectResponse(BaseModel):
    """项目响应（``Project`` 聚合根的对外视图）。"""

    id: str
    tenant_id: str | None = None
    organization_id: str | None = None
    workspace_id: str = ""
    name: str = ""
    description: str | None = None
    repo_url: str | None = None
    default_branch: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FileObjectResponse(BaseModel):
    """工作区文件对象元数据响应（``Storage.list`` 的 ``StoredObject`` 视图）。"""

    key: str
    size: int = 0
    content_type: str | None = None
    etag: str | None = None
    created_at: datetime | None = None


class FileContentResponse(BaseModel):
    """工作区文件内容响应（读取**经 ``Storage``**；内容以 base64 承载，二进制安全）。"""

    path: str
    size: int = 0
    encoding: str = "base64"
    content_base64: str = ""


class EnvironmentVarResponse(BaseModel):
    """单个环境变量响应（敏感项 ``masked=True``，仅返回引用，**不回显明文**）。"""

    name: str
    value: str | None = Field(default=None, description="非敏感项明文（敏感项恒 None）")
    ref: str | None = Field(default=None, description="敏感项引用：credential:<id> / secret:<NAME>")
    masked: bool = Field(default=False, description="敏感项标记（True 时 value 恒 None）")


class EnvironmentResponse(BaseModel):
    """工作区运行环境响应（``WorkspaceEnvironment`` 的对外视图；敏感项 masked）。"""

    id: str
    tenant_id: str | None = None
    organization_id: str | None = None
    workspace_id: str = ""
    name: str = ""
    env_vars: list[EnvironmentVarResponse] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# -- R3 / T2-60：远程 Project 视图 -------------------------------------------


class CloneProjectRequest(BaseModel):
    """Project Clone 请求（F-R1；``base_ref`` / ``idempotency_key`` 可空）。"""

    base_ref: str | None = Field(default=None, description="克隆基准引用（可空）")
    idempotency_key: str | None = Field(default=None, description="幂等键（可空）")


class CloneProjectResponse(BaseModel):
    """Project Clone 响应（``202 {task_id}``；异步派发 ``project.clone``）。"""

    task_id: str


class ProjectStatusResponse(BaseModel):
    """远程 Project 状态视图（**不含宿主路径**）。"""

    project_id: str
    name: str = ""
    workspace_id: str = ""
    tenant_id: str | None = None
    default_branch: str | None = None
    repo_configured: bool = False
    clone_task_id: str | None = None
    refs_available: bool = False


class GitRefResponse(BaseModel):
    """Git 引用视图（分支 / 标签；**不含宿主路径**）。"""

    name: str
    commit: str | None = None
    kind: str = "branch"
