"""``http`` Tool（设计 §2.5.2）：出网请求，**默认拒绝全部** + SSRF 防护。

- 出网判定**统一入口**＝``astra_security.egress.SecurityEgressPolicy``（W1 / T2-03）：
  经 :attr:`~astra_tool.context.ToolContext.egress_policy` **注入**优先使用；
- **缺省**（未注入）退回 Phase 1 语义：按 ``permission_scope.allow`` 白名单经
  :func:`astra_tool.security.check_egress` 校验，**出网默认拒绝全部**（§5 #5）；
- SSRF 防护见 :mod:`astra_tool.security`（内网 IP / 元数据端点 / DNS rebinding）。
"""

from __future__ import annotations

import urllib.request
from typing import Any

from astra_core import ErrorCode

from ..base import BaseTool, ToolMetadata, ToolPermissionRequirement, ToolResult, ToolSpec
from ..security import check_egress

__all__ = ["HttpTool"]


class HttpTool(BaseTool):
    """HTTP 请求工具（默认拒绝全部出网，仅显式白名单放行）。"""

    SPEC = ToolSpec(
        metadata=ToolMetadata(
            name="http",
            display_name="HTTP",
            description="发起 HTTP 请求（出网默认拒绝，需显式白名单）",
            category="network",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 1},
                "method": {"type": "string"},
                "headers": {"type": "object"},
                "body": {"type": "string"},
                "timeout_ms": {"type": "integer", "minimum": 1},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        permission=ToolPermissionRequirement(action="EXECUTE"),
        requires_sandbox=False,
    )

    def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        """校验出网策略后执行请求。

        出网判定**优先**使用注入的 ``EgressPolicy``（``ctx.egress_policy``）；缺省时退回
        Phase 1 语义（``permission_scope.allow`` 白名单 + ``check_egress``，**默认拒绝全部**）。
        """
        url = str(args["url"])

        policy = getattr(ctx, "egress_policy", None)
        if policy is not None:
            # 唯一出网入口：拒绝即 raise DomainError(PERMISSION_DENIED)。
            policy.enforce(url)
        else:
            # 缺省：默认拒绝全部（未命中白名单即抛 PERMISSION_DENIED）。
            scope = getattr(ctx, "permission_scope", None)
            allowlist = list(scope.allow) if scope is not None else None
            check_egress(url, allowlist=allowlist)

        method = str(args.get("method") or "GET").upper()
        headers = {str(k): str(v) for k, v in (args.get("headers") or {}).items()}
        body = args.get("body")
        timeout_ms = args.get("timeout_ms")
        timeout = (float(timeout_ms) / 1000.0) if timeout_ms else 30.0
        data = body.encode("utf-8") if isinstance(body, str) else None

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = response.read().decode("utf-8", errors="replace")
                return ToolResult.success(
                    payload,
                    status=response.status,
                    url=url,
                    method=method,
                )
        except Exception as exc:  # noqa: BLE001 - 统一映射为工具失败
            return ToolResult.failure(
                f"HTTP 请求失败：{exc}", code=ErrorCode.INTERNAL_ERROR.value, url=url
            )
