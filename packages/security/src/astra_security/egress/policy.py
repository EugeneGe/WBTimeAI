"""``SecurityEgressPolicy``——**唯一出网判定入口**（W1 / T2-03；设计 §2.18）。

配置驱动 allow / deny + ``deny_private`` + **重定向逐跳** + 超时 + 审计；原语复用
:mod:`astra_domain.ports.egress`（**单一来源**，W1 裁定 §4.1 / §4.2）。

公开 API（裁定 §4.3）：

- :meth:`authorize` / :meth:`authorize_redirect`：**不抛**，返回 :class:`EgressDecision`；
- :meth:`enforce`：拒绝即 ``raise DomainError(PERMISSION_DENIED)``，放行返回**钉定 IP**。

算法（裁定 §4.4）：scheme 限 ``http/https``；**默认拒绝全部**（空 allow）；强制拒段
（白名单**不可**覆盖）；DNS 全量校验 + 二次解析防 rebinding；重定向逐跳（跳数超限拒）；
拒绝与放行均**非静默**（审计 ``action="egress.request"``）。
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

from astra_core import DomainError, ErrorCode
from astra_domain import AUDIT_OUTCOME_DENIED, AUDIT_OUTCOME_SUCCESS, AuditLog
from astra_domain.ports.egress import (
    ALLOWED_SCHEMES,
    EgressDecision,
    host_matches,
    is_blocked_ip,
)

from .dns import resolve_and_validate

__all__ = [
    "EGRESS_ACTION",
    "EGRESS_WIRING_POINTS",
    "EgressWiringPoint",
    "SecurityEgressPolicy",
]

_logger = logging.getLogger("astra_security.egress")

#: 审计动作（设计 §2.18 / 裁定 §4.4）。
EGRESS_ACTION = "egress.request"


@dataclass(frozen=True)
class EgressWiringPoint:
    """出网面接线点（设计 §2.18 / 裁定 §4.6；``I-P2-32`` / DoD ``D14``）。

    Attributes:
        name: 出网面名（``http_tool`` / ``mcp_endpoint`` / ``knowledge_url`` / ``webhook``）。
        location: 精确接线点（``模块.符号``）。
        status: ``implemented``（W1 实装）/ ``declared``（声明 + 接线点，实装归后续波次）。
        owner_task: 归属任务。
    """

    name: str
    location: str
    status: str
    owner_task: str


#: 四个出网面接线点（W1：① 实装；②③④ 声明 + 接线点）。
EGRESS_WIRING_POINTS: tuple[EgressWiringPoint, ...] = (
    EgressWiringPoint(
        name="http_tool",
        location="astra_tool.tools.http.HttpTool.run",
        status="implemented",
        owner_task="T2-03",
    ),
    EgressWiringPoint(
        name="mcp_endpoint",
        location="astra_mcp.client.MCPClient.connect",
        status="declared",
        owner_task="T2-11",
    ),
    EgressWiringPoint(
        name="knowledge_url",
        location="astra_knowledge.parser.UrlFetcher.fetch",
        status="declared",
        owner_task="T2-28",
    ),
    EgressWiringPoint(
        name="webhook_callback",
        location="astra_workflow.webhook.WebhookInvoker.invoke",
        status="declared",
        owner_task="T2-39",
    ),
)


class SecurityEgressPolicy:
    """出网策略（**唯一入口** 具体实现；设计 §2.18）。

    Attributes:
        enabled: 总开关（默认开）；配合空 ``allow`` ⇒ 默认拒绝全部。
        allow: 默认白名单（域名 glob / IP 字面）。
        deny_private: 是否强制拒绝拒段（**不可被 allow 覆盖**）。
        connect_timeout_seconds: 连接超时（秒）。
        read_timeout_seconds: 读取超时（秒）。
        max_redirects: 重定向最大跳数。
        log_allowed: 是否记录放行审计。
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        allow: Sequence[str] = (),
        deny_private: bool = True,
        connect_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 30.0,
        max_redirects: int = 5,
        log_allowed: bool = False,
        resolver: Callable[[str], Iterable[str]] | None = None,
        audit_repository: Any | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        request_id: str = "",
    ) -> None:
        """构造出网策略。

        Args:
            enabled: 总开关。
            allow: 默认白名单（**首批为空**，部署方显式添加）。
            deny_private: 是否强制拒绝拒段。
            connect_timeout_seconds: 连接超时（秒）。
            read_timeout_seconds: 读取超时（秒）。
            max_redirects: 重定向最大跳数。
            log_allowed: 是否记录放行审计。
            resolver: 可注入 DNS 解析器（测试用）。
            audit_repository: 注入的 :class:`~astra_domain.AuditRepository`（可空）。
            tenant_id: 审计租户归属（可空）。
            workspace_id: 审计工作区归属（可空）。
            request_id: 审计请求标识（幂等去重键）。
        """
        self._enabled = enabled
        self._allow: tuple[str, ...] = tuple(allow or ())
        self._deny_private = deny_private
        self._connect_timeout = connect_timeout_seconds
        self._read_timeout = read_timeout_seconds
        self._max_redirects = max_redirects
        self._log_allowed = log_allowed
        self._resolver = resolver
        self._audit = audit_repository
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._request_id = request_id

    @classmethod
    def from_settings(
        cls,
        settings: Any,
        *,
        resolver: Callable[[str], Iterable[str]] | None = None,
        audit_repository: Any | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
        request_id: str = "",
    ) -> SecurityEgressPolicy:
        """由 :class:`~astra_config.settings.Settings` 的 ``egress`` 嵌套配置构建策略。

        Args:
            settings: 生效配置（读 ``settings.egress``）。
            resolver: 可注入 DNS 解析器。
            audit_repository: 注入的审计仓储。
            tenant_id: 审计租户归属。
            workspace_id: 审计工作区归属。
            request_id: 审计请求标识。

        Returns:
            配置驱动的 :class:`SecurityEgressPolicy`。
        """
        egress = getattr(settings, "egress", None)
        kwargs: dict[str, Any] = {
            "resolver": resolver,
            "audit_repository": audit_repository,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "request_id": request_id,
        }
        if egress is None:  # pragma: no cover - Settings 恒带 egress
            return cls(**kwargs)
        return cls(
            enabled=bool(getattr(egress, "enabled", True)),
            allow=list(getattr(egress, "allow", []) or []),
            deny_private=bool(getattr(egress, "deny_private", True)),
            connect_timeout_seconds=float(getattr(egress, "connect_timeout_seconds", 10.0)),
            read_timeout_seconds=float(getattr(egress, "read_timeout_seconds", 30.0)),
            max_redirects=int(getattr(egress, "max_redirects", 5)),
            log_allowed=bool(getattr(egress, "log_allowed", False)),
            **kwargs,
        )

    # -- 属性（只读） -------------------------------------------------------

    @property
    def connect_timeout_seconds(self) -> float:
        """连接超时（秒）。"""
        return self._connect_timeout

    @property
    def read_timeout_seconds(self) -> float:
        """读取超时（秒）。"""
        return self._read_timeout

    @property
    def max_redirects(self) -> int:
        """重定向最大跳数。"""
        return self._max_redirects

    # -- 公开 API -----------------------------------------------------------

    def authorize(
        self,
        url: str,
        *,
        allow: Sequence[str] | None = None,
        deny_private: bool | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
    ) -> EgressDecision:
        """校验单个 URL（**不抛**，返回决策）。

        Args:
            url: 目标 URL。
            allow: 本次调用的白名单覆盖（``None`` 用策略默认）。
            deny_private: 本次调用的拒段开关覆盖（``None`` 用策略默认）。
            resolver: 本次调用的解析器覆盖。

        Returns:
            :class:`EgressDecision`。
        """
        decision = self._check(
            url, allow=allow, deny_private=deny_private, resolver=resolver, chain=()
        )
        self._record(decision)
        return decision

    def authorize_redirect(
        self,
        *,
        from_url: str,
        location: str,
        allow: Sequence[str] | None = None,
        deny_private: bool | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
        chain: tuple[str, ...] = (),
    ) -> EgressDecision:
        """校验一次重定向（**不抛**；以 ``location`` 重跑逐跳校验）。

        Args:
            from_url: 重定向来源 URL（用于解析相对 ``location``）。
            location: ``Location`` 头（绝对 / 相对）。
            allow: 白名单覆盖。
            deny_private: 拒段开关覆盖。
            resolver: 解析器覆盖。
            chain: 已走过的跳（累加）。

        Returns:
            :class:`EgressDecision`。
        """
        target = urljoin(from_url, location)
        new_chain = (*chain, target)
        if len(new_chain) > self._max_redirects:
            decision = EgressDecision(
                allowed=False,
                code=ErrorCode.PERMISSION_DENIED,
                reason=f"重定向跳数超限（>{self._max_redirects}）",
                host=urlsplit(target).hostname or "",
                resolved_ip=None,
                chain=chain,
            )
            self._record(decision)
            return decision
        decision = self._check(
            target, allow=allow, deny_private=deny_private, resolver=resolver, chain=new_chain
        )
        self._record(decision)
        return decision

    def enforce(
        self,
        url: str,
        *,
        allow: Sequence[str] | None = None,
        deny_private: bool | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
    ) -> str:
        """强制校验（拒绝即抛 ``DomainError(PERMISSION_DENIED)``；放行返回钉定 IP）。

        Args:
            url: 目标 URL。
            allow: 白名单覆盖。
            deny_private: 拒段开关覆盖。
            resolver: 解析器覆盖。

        Returns:
            放行时**钉定**的 IP（供连接使用）。

        Raises:
            DomainError: 拒绝出网（``PERMISSION_DENIED``）。
        """
        decision = self.authorize(url, allow=allow, deny_private=deny_private, resolver=resolver)
        if not decision.allowed:
            raise DomainError(
                decision.reason,
                code=ErrorCode.PERMISSION_DENIED,
                data={"url": url, "host": decision.host, "reason": decision.reason},
            )
        return decision.resolved_ip or ""

    # -- 内部 ---------------------------------------------------------------

    def _check(
        self,
        url: str,
        *,
        allow: Sequence[str] | None,
        deny_private: bool | None,
        resolver: Callable[[str], Iterable[str]] | None,
        chain: tuple[str, ...],
    ) -> EgressDecision:
        """核心校验（1–4 步；返回决策）。"""
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if not self._enabled:
            return EgressDecision(True, ErrorCode.UNKNOWN, "出网策略已禁用", host, None, chain)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            return self._deny("非法的出网协议", host, chain)
        if not host:
            return self._deny("缺少目标 host", host, chain)

        effective_allow = tuple(allow) if allow is not None else self._allow
        if not host_matches(host, effective_allow):
            return self._deny("出网默认拒绝（未命中白名单）", host, chain)

        effective_deny_private = self._deny_private if deny_private is None else deny_private
        effective_resolver = resolver if resolver is not None else self._resolver

        # IP 直连：直接校验拒段。
        try:
            ipaddress.ip_address(host)
            literal = True
        except ValueError:
            literal = False

        if literal:
            if effective_deny_private and is_blocked_ip(host):
                return self._deny("拒绝访问内网 / 元数据地址", host, chain)
            return EgressDecision(True, ErrorCode.UNKNOWN, "放行（IP 直连）", host, host, chain)

        ips, violation = resolve_and_validate(
            host, resolver=effective_resolver, deny_private=effective_deny_private
        )
        if violation is not None:
            return self._deny(violation, host, chain)
        pinned = ips[0] if ips else None
        if pinned is None:
            return self._deny("域名无解析结果", host, chain)
        return EgressDecision(True, ErrorCode.UNKNOWN, "放行", host, pinned, chain)

    @staticmethod
    def _deny(reason: str, host: str, chain: tuple[str, ...]) -> EgressDecision:
        """构造拒绝决策（``PERMISSION_DENIED``）。"""
        return EgressDecision(
            allowed=False,
            code=ErrorCode.PERMISSION_DENIED,
            reason=reason,
            host=host,
            resolved_ip=None,
            chain=chain,
        )

    def _record(self, decision: EgressDecision) -> None:
        """记录决策（**非静默**：先记日志，再可选落审计 ``action=egress.request``）。"""
        if not decision.allowed:
            _logger.warning(
                "egress.denied",
                extra={
                    "host": decision.host,
                    "reason": decision.reason,
                    "chain": list(decision.chain),
                },
            )
        elif self._log_allowed:
            _logger.info(
                "egress.allowed",
                extra={"host": decision.host, "resolved_ip": decision.resolved_ip},
            )

        if self._audit is None:
            return
        if decision.allowed and not self._log_allowed:
            return
        record = AuditLog(
            tenant_id=self._tenant_id,
            workspace_id=self._workspace_id,
            action=EGRESS_ACTION,
            outcome=AUDIT_OUTCOME_SUCCESS if decision.allowed else AUDIT_OUTCOME_DENIED,
            request_id=self._request_id,
            metadata={
                "host": decision.host,
                "resolved_ip": decision.resolved_ip,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "chain": list(decision.chain),
            },
        )
        try:
            self._audit.add(record)
        except Exception:  # noqa: BLE001 - 审计失败不得影响出网判定（不静默：记日志）
            _logger.exception("egress.audit_failed", extra={"host": decision.host})
