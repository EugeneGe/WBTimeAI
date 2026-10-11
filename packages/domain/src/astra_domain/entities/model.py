"""Model 组领域实体（设计 §2.15.1 Model 组 / §2.3）。

纯 dataclass，零框架依赖（C-03）。

- :class:`ModelProvider`：模型提供方（凭证**复用** ``credential``，C-07）；
- :class:`Model`：模型目录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import MODEL_PROVIDER_STATUS_ACTIVE, MODEL_STATUS_ACTIVE, MODEL_TYPE_CHAT
from .base import AggregateRoot

__all__ = ["ModelProvider", "Model"]


@dataclass
class ModelProvider(AggregateRoot):
    """模型提供方.

    Attributes:
        workspace_id: 归属工作区标识（可空）。
        name: 提供方名称。
        type: 提供方类型（如 ``openai`` / ``ollama`` / ``openai_compatible``）。
        endpoint: 自定义端点（可空）。
        credential_id: 凭证标识（复用 ``credential`` 表，可空）。
        status: 状态（``MODEL_PROVIDER_STATUS_*``）。
        config: 附加配置（JSON 结构）。
    """

    workspace_id: str | None = None
    name: str = ""
    type: str = ""
    endpoint: str | None = None
    credential_id: str | None = None
    status: str = MODEL_PROVIDER_STATUS_ACTIVE
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Model(AggregateRoot):
    """模型目录.

    Attributes:
        provider_id: 所属提供方标识。
        name: 模型名（如 ``gpt-4o``）。
        type: 模型类型（``MODEL_TYPE_*``）。
        context_window: 上下文窗口（可空）。
        capabilities: 能力声明（JSON 结构）。
        status: 状态（``MODEL_STATUS_*``）。
    """

    provider_id: str = ""
    name: str = ""
    type: str = MODEL_TYPE_CHAT
    context_window: int | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    status: str = MODEL_STATUS_ACTIVE
