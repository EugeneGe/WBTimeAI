"""``SecurityEgressPolicy`` 单测（W1 / T2-03；设计 §2.18 / ``I-P2-32``）。

覆盖：默认拒绝全部 / 白名单放行 / 拒段不可被白名单覆盖（含 ``169.254.169.254``）/
IP 直连拒段 / scheme 限制 / 重定向逐跳 + 跳数超限 / DNS rebinding / 审计 /
``enforce`` 抛 ``DomainError(PERMISSION_DENIED)``。``mark security``。
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from astra_core import DomainError, ErrorCode
from astra_domain.ports.egress import METADATA_IPS
from astra_security.egress import SecurityEgressPolicy

pytestmark = pytest.mark.security


def _rebinding_resolver() -> object:
    """DNS rebinding：首解析公网、二次解析内网。"""
    state = {"n": 0}

    def resolver(host: str) -> list[str]:
        state["n"] += 1
        return ["93.184.216.34"] if state["n"] == 1 else ["127.0.0.1"]

    return resolver


def test_default_deny_all() -> None:
    """默认（enabled + 空 allow）⇒ 拒绝全部出网。"""
    decision = SecurityEgressPolicy().authorize("https://example.com/")
    assert decision.allowed is False
    assert decision.code is ErrorCode.PERMISSION_DENIED


def test_metadata_ip_denied_when_allowlisted() -> None:
    """``169.254.169.254`` 即使显式加入白名单也被强制拒段拦截。"""
    assert "169.254.169.254" in METADATA_IPS
    policy = SecurityEgressPolicy(allow=["169.254.169.254"])
    decision = policy.authorize("http://169.254.169.254/latest/meta-data/")
    assert decision.allowed is False
    assert decision.code is ErrorCode.PERMISSION_DENIED


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ],
)
def test_private_ip_literal_denied(url: str) -> None:
    """私网 / 环回 IP 直连拒段。"""
    host = url.split("//", 1)[1].split("/", 1)[0].strip("[]")
    policy = SecurityEgressPolicy(allow=[host])
    assert policy.authorize(url).allowed is False


def test_allowlisted_public_host_ok_pins_ip() -> None:
    """白名单公网域名放行，并返回钉定 IP。"""
    policy = SecurityEgressPolicy(allow=["example.com"])
    decision = policy.authorize("https://example.com/", resolver=lambda host: ["93.184.216.34"])
    assert decision.allowed is True
    assert decision.resolved_ip == "93.184.216.34"


def test_scheme_restriction() -> None:
    """非 ``http`` / ``https`` scheme 拒绝。"""
    policy = SecurityEgressPolicy(allow=["example.com"])
    assert policy.authorize("ftp://example.com/x").allowed is False


def test_dns_rebinding_denied() -> None:
    """首解析公网、二次解析内网 ⇒ 拒（DNS rebinding）。"""
    policy = SecurityEgressPolicy(allow=["rebind.example.com"])
    decision = policy.authorize("http://rebind.example.com/", resolver=_rebinding_resolver())
    assert decision.allowed is False
    assert decision.code is ErrorCode.PERMISSION_DENIED


def test_redirect_to_internal_denied() -> None:
    """重定向逐跳：公网 → 内网被拦。"""
    policy = SecurityEgressPolicy(allow=["good.example.com"])
    decision = policy.authorize_redirect(
        from_url="https://good.example.com/start",
        location="http://169.254.169.254/",
    )
    assert decision.allowed is False


def test_redirect_hop_limit_exceeded() -> None:
    """重定向跳数超 ``max_redirects`` ⇒ 拒。"""
    policy = SecurityEgressPolicy(allow=["good.example.com"], max_redirects=1)
    chain = ("https://good.example.com/0", "https://good.example.com/1")
    decision = policy.authorize_redirect(
        from_url="https://good.example.com/2", location="/3", chain=chain
    )
    assert decision.allowed is False
    assert "跳数" in decision.reason


def test_redirect_relative_location_resolved() -> None:
    """相对 ``location`` 以 ``from_url`` 解析后校验（公网放行）。"""
    policy = SecurityEgressPolicy(allow=["good.example.com"])
    decision = policy.authorize_redirect(
        from_url="https://good.example.com/start",
        location="/next",
        resolver=lambda host: ["93.184.216.34"],
    )
    assert decision.allowed is True


def test_enforce_raises_permission_denied() -> None:
    """``enforce`` 拒绝即抛 ``DomainError(PERMISSION_DENIED)``。"""
    with pytest.raises(DomainError) as excinfo:
        SecurityEgressPolicy().enforce("https://example.com/")
    assert excinfo.value.code is ErrorCode.PERMISSION_DENIED


def test_enforce_returns_pinned_ip() -> None:
    """``enforce`` 放行返回钉定 IP。"""
    policy = SecurityEgressPolicy(allow=["example.com"])
    pinned = policy.enforce("https://example.com/", resolver=lambda host: ["93.184.216.34"])
    assert pinned == "93.184.216.34"


def test_audit_records_denied_request() -> None:
    """拒绝落审计（``action=egress.request``）。"""

    class _Repo:
        def __init__(self) -> None:
            self.records: list[object] = []

        def add(self, record: object) -> object:
            self.records.append(record)
            return record

    repo = _Repo()
    policy = SecurityEgressPolicy(audit_repository=repo, request_id="req-1")
    policy.authorize("https://example.com/")
    assert repo.records
    assert repo.records[0].action == "egress.request"


def test_disabled_policy_allows() -> None:
    """``enabled=False`` 时策略失效（直接放行）。"""
    decision = SecurityEgressPolicy(enabled=False).authorize("https://example.com/")
    assert decision.allowed is True


def test_custom_resolver_iterable() -> None:
    """可注入返回 ``Iterable`` 的解析器。"""

    def resolver(host: str) -> Iterable[str]:
        return ("93.184.216.34",)

    policy = SecurityEgressPolicy(allow=["example.com"])
    assert policy.authorize("https://example.com/", resolver=resolver).allowed is True
