"""Feature Flag SQL 存储（``SqlFeatureFlagStore``，T0-21）。

实现 :class:`astra_config.feature_flags.FeatureFlagStore` 协议：从 ``feature_flag``
表读取覆盖（``name`` → ``enabled``）。

🔴 **降级优先**：表缺失 / 读取异常 → **返回 ``{}``（不抛）**，
   保证关闭任一 / 全部 flag（乃至整张表缺失）时应用**仍可启动**（§3-#14）。

本模块属 ``astra_database``，仅依赖 SQLAlchemy 与 ``astra_config`` 的**协议类型**
（无第三方 Web 依赖）；不得被 Router 直接引用（Router 经 ``AppServices``）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models.feature_flag import FeatureFlag

__all__ = ["SqlFeatureFlagStore"]

_logger = logging.getLogger("astra_database.feature_flags")


class SqlFeatureFlagStore:
    """基于 ``feature_flag`` 表的覆盖存储。

    Attributes:
        session_factory: SQLAlchemy 会话工厂（``sessionmaker``）。
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """初始化。

        Args:
            session_factory: 会话工厂。
        """
        self._session_factory = session_factory

    def load_overrides(self) -> dict[str, bool]:
        """读取全部 flag 覆盖。

        表缺失 / 连接 / 读取异常时**返回空字典**（降级，不抛）。

        Returns:
            ``name`` → ``enabled`` 映射；无覆盖或读取失败时为空字典。
        """
        try:
            with self._session_factory() as session:
                rows = session.execute(select(FeatureFlag.name, FeatureFlag.enabled)).all()
        except Exception as exc:  # noqa: BLE001 - 表缺失 / 读异常 → 降级为空覆盖
            _logger.warning(
                "feature_flag.store_unavailable",
                extra={
                    "event": "feature_flag.store_unavailable",
                    "error": type(exc).__name__,
                },
            )
            return {}

        overrides: dict[str, bool] = {}
        for name, enabled in rows:
            if name is None:
                continue
            overrides[str(name)] = bool(enabled)
        return overrides

    def upsert(
        self,
        name: str,
        enabled: bool,
        description: str | None = None,
    ) -> FeatureFlag:
        """运维用：写入 / 更新单条 flag 覆盖（幂等）。

        Args:
            name: flag 名称。
            enabled: 是否启用。
            description: 可选说明（``None`` 时保留既有说明）。

        Returns:
            写入后的 :class:`FeatureFlag` 实体。

        Raises:
            Exception: 表缺失 / 写失败时向上抛出（运维显式操作，非启动路径）。
        """
        with self._session_factory() as session:
            existing: Any = session.execute(
                select(FeatureFlag).where(FeatureFlag.name == name)
            ).scalar_one_or_none()
            if existing is None:
                existing = FeatureFlag(name=name, enabled=enabled, description=description)
                session.add(existing)
            else:
                existing.enabled = enabled
                if description is not None:
                    existing.description = description
            session.commit()
            session.refresh(existing)
            return existing
