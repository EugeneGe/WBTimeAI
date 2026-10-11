"""四出网面均受控断言（W1 / T2-03；设计 §2.18 / ``I-P2-32`` / DoD ``D14``）。

W1 状态：① HTTP Tool **实装**（经注入 ``EgressPolicy`` 或退回归一语义）；
② ``mcp_server.endpoint`` / ③ ``document.source_type=url`` / ④ Webhook 回调
**声明 + 接线点**（实装归 W2 / W5 / W7），以接线点注册表断言「必经 ``EgressPolicy``」。
``mark security``。
"""

from __future__ import annotations

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain.ports.egress import METADATA_IPS as DOMAIN_METADATA_IPS
from astra_security.egress import EGRESS_WIRING_POINTS, SecurityEgressPolicy
from astra_tool import HttpTool, ToolContext
from astra_tool.security import METADATA_IPS as TOOL_METADATA_IPS

pytestmark = pytest.mark.security


def test_http_tool_default_deny_still_green() -> None:
    """① HTTP Tool 缺省（未注入策略）仍**默认拒绝全部**（Phase 1 冻结语义保持）。"""
    with pytest.raises(DomainError):
        HttpTool().execute({"url": "https://example.com/"}, ToolContext())


def test_http_tool_uses_injected_egress_policy() -> None:
    """① HTTP Tool **优先**取注入的 ``EgressPolicy``（拒绝即抛）。"""
    ctx = ToolContext(egress_policy=SecurityEgressPolicy())
    with pytest.raises(DomainError) as excinfo:
        HttpTool().execute({"url": "https://example.com/"}, ctx)
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_four_egress_faces_are_covered() -> None:
    """②③④ 接线点 + ① 实装：四出网面均在 ``EGRESS_WIRING_POINTS`` 注册。"""
    by_name = {point.name: point for point in EGRESS_WIRING_POINTS}
    assert set(by_name) == {"http_tool", "mcp_endpoint", "knowledge_url", "webhook_callback"}
    assert by_name["http_tool"].status == "implemented"
    for name in ("mcp_endpoint", "knowledge_url", "webhook_callback"):
        assert by_name[name].status == "declared"
        assert by_name[name].location  # 精确接线点非空


def test_egress_primitives_are_single_source() -> None:
    """单一来源：``astra_tool.security.METADATA_IPS`` 与 domain 原语一致（薄委托）。"""
    assert TOOL_METADATA_IPS == DOMAIN_METADATA_IPS
    assert "169.254.169.254" in TOOL_METADATA_IPS
