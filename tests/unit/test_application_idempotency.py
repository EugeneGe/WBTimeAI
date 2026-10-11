"""幂等记录读写单测（W6 / T1-29；裁定 Q4/A28）。

零 ORM：以 **fake 仓储**驱动 :class:`~astra_application.IdempotencyService`，
断言「请求指纹 + 命中判定」口径：

- :func:`compute_request_fingerprint`：确定性 sha256 hex（64 字符）、随 body 变化；
- ``lookup``：无键 → ``None``；未命中 → ``None``；命中用户一致 + 指纹一致 → 复用首次 Run；
  命中但**用户不一致** / **指纹不一致** → ``DomainError(IDEMPOTENCY_KEY_REUSE)``（→ 409）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from astra_application import IdempotencyService, compute_request_fingerprint
from astra_core import DomainError, ErrorCode
from astra_domain import AgentRun

#: 指纹存于 ``task.payload`` 的键名（与实现约定一致）。
_FINGERPRINT_KEY = "request_fingerprint"


class FakeRuns:
    """伪 ``AgentRunRepository``（仅实现 ``get_by_idempotency_key``）。"""

    def __init__(self, run: AgentRun | None) -> None:
        self._run = run

    def get_by_idempotency_key(self, tenant_id: str, idempotency_key: str) -> AgentRun | None:
        if self._run is None:
            return None
        if self._run.tenant_id != tenant_id or self._run.idempotency_key != idempotency_key:
            return None
        return self._run


class FakeTasks:
    """伪 ``TaskRepository``（仅实现 ``get``）。"""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self._payload = payload

    def get(self, task_id: str) -> Any:
        if self._payload is None:
            return None
        return SimpleNamespace(task_id=task_id, payload=self._payload)


def _service(run: AgentRun | None, payload: dict[str, Any] | None) -> IdempotencyService:
    return IdempotencyService(
        runs=cast(Any, FakeRuns(run)),
        tasks=cast(Any, FakeTasks(payload)),
    )


def _run(*, user_id: str = "u1", task_id: str = "task-1") -> AgentRun:
    return AgentRun(
        id="run-1",
        tenant_id="t1",
        agent_id="a1",
        agent_version_id="v1",
        conversation_id="c1",
        user_id=user_id,
        task_id=task_id,
        idempotency_key="k1",
    )


# -- 指纹 --------------------------------------------------------------------


def test_fingerprint_is_deterministic_hex_sha256() -> None:
    """同一 body → 相同指纹；不同 body → 不同指纹；格式为 64 位小写 hex。"""
    fp1 = compute_request_fingerprint(agent_id="a", conversation_id="c", input="hi")
    fp2 = compute_request_fingerprint(agent_id="a", conversation_id="c", input="hi")
    fp3 = compute_request_fingerprint(agent_id="a", conversation_id="c", input="bye")
    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 64
    assert all(ch in "0123456789abcdef" for ch in fp1)


def test_fingerprint_includes_permission_scope_when_present() -> None:
    """提供 ``permission_scope`` 时纳入指纹（可与不提供者区分）。"""
    without = compute_request_fingerprint(agent_id="a", conversation_id="c", input="hi")
    with_scope = compute_request_fingerprint(
        agent_id="a", conversation_id="c", input="hi", permission_scope={"allow": ["read"]}
    )
    assert without != with_scope


# -- lookup ------------------------------------------------------------------


def test_lookup_returns_none_without_key() -> None:
    """空键 → 不启用幂等（``None``）。"""
    service = _service(_run(), {_FINGERPRINT_KEY: "any"})
    assert (
        service.lookup(
            tenant_id="t1", idempotency_key="", current_user_id="u1", request_fingerprint="x"
        )
        is None
    )


def test_lookup_returns_none_when_not_found() -> None:
    """未命中 → ``None``（由调用方继续首次执行）。"""
    service = _service(None, None)
    assert (
        service.lookup(
            tenant_id="t1", idempotency_key="k1", current_user_id="u1", request_fingerprint="x"
        )
        is None
    )


def test_lookup_reuses_first_run_on_user_and_fingerprint_match() -> None:
    """命中用户一致 + 指纹一致 → 复用首次 Run。"""
    fingerprint = "f" * 64
    service = _service(_run(user_id="u1"), {_FINGERPRINT_KEY: fingerprint})
    found = service.lookup(
        tenant_id="t1",
        idempotency_key="k1",
        current_user_id="u1",
        request_fingerprint=fingerprint,
    )
    assert found is not None and found.id == "run-1"


def test_lookup_conflicts_on_cross_user() -> None:
    """命中但用户不一致 → ``IDEMPOTENCY_KEY_REUSE``（防跨用户串号，→ 409）。"""
    service = _service(_run(user_id="u1"), {_FINGERPRINT_KEY: "f" * 64})
    with pytest.raises(DomainError) as excinfo:
        service.lookup(
            tenant_id="t1",
            idempotency_key="k1",
            current_user_id="u2",
            request_fingerprint="f" * 64,
        )
    assert excinfo.value.code == ErrorCode.IDEMPOTENCY_KEY_REUSE


def test_lookup_conflicts_on_same_key_different_body() -> None:
    """命中用户一致但指纹不一致（同键不同体）→ ``IDEMPOTENCY_KEY_REUSE``（→ 409）。"""
    service = _service(_run(user_id="u1"), {_FINGERPRINT_KEY: "a" * 64})
    with pytest.raises(DomainError) as excinfo:
        service.lookup(
            tenant_id="t1",
            idempotency_key="k1",
            current_user_id="u1",
            request_fingerprint="b" * 64,
        )
    assert excinfo.value.code == ErrorCode.IDEMPOTENCY_KEY_REUSE
