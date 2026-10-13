"""审计写入失败降级与重放集成测试（设计 §2.18.2 / N-12）。

覆盖验收口径：
① 正常写入成功落 ``audit_log``；② ``AuditSink`` 抛异常 → 降级本地落盘 + 告警日志 +
   业务不中断；③ 落盘也失败 → 提升 ``ERROR`` 结构化日志 + ``audit_write_failure_total`` 计数；
④ 重放幂等（同 ``request_id`` 不重复入库）；⑤ ``metadata`` 中凭证一律掩码（无明文）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from astra_application.dto.audit import AuditRecordDTO
from astra_application.services import (
    AUDIT_WRITE_FAILURE_TOTAL,
    AuditService,
    AuditSpool,
)
from astra_database import SqlAuditRepository
from astra_domain import AuditLog

_PLAINTEXT_KEY = "sk-abcdefghijklmnop1234567890"


class _BoomSink:
    """写库即抛异常的假 sink（模拟 DB 不可用）。"""

    def write(self, record: AuditLog) -> None:  # noqa: D401
        raise RuntimeError("database unavailable")


class _BoomSpool(AuditSpool):
    """落盘即抛异常的假 spool（模拟磁盘不可写）。"""

    def write(self, record: AuditLog) -> Path:  # type: ignore[override]
        raise OSError("disk full")


class _RecordingMetrics:
    """记录计数的假指标汇。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def counter(self, name: str, value: int = 1, **tags: object) -> None:
        self.calls.append((name, value))


def test_audit_normal_write_persists_masked(session_factory, tmp_path: Path) -> None:
    """① 正常写入成功落 ``audit_log``；⑤ metadata 凭证被掩码（无明文）。"""
    repository = SqlAuditRepository(session_factory)
    service = AuditService(repository=repository, spool=AuditSpool(tmp_path / "spool"))

    record = service.record(
        AuditRecordDTO(
            tenant_id="t-1",
            action="tool_call",
            request_id="req-normal",
            user_id="u-1",
            metadata={"api_key": _PLAINTEXT_KEY, "path": "/workspace/a.txt"},
        )
    )
    assert record.request_id == "req-normal"
    assert repository.exists_request_id("req-normal") is True

    from astra_database.models.audit import AuditLog as OrmAuditLog

    with session_factory() as session:
        row = session.query(OrmAuditLog).filter_by(request_id="req-normal").one()
        dumped = json.dumps(row.metadata_)
        assert _PLAINTEXT_KEY not in dumped
        assert row.metadata_["path"] == "/workspace/a.txt"
        assert (
            "sk-" not in json.dumps(row.metadata_["api_key"]) or "..." in row.metadata_["api_key"]
        )


def test_audit_sink_failure_falls_back_to_spool(
    tmp_path: Path, caplog: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """② 写库抛异常 → 降级本地落盘 + 告警日志 + 业务不中断。"""
    # P2.7-B：显式隔离 logger——in-process ``alembic fileConfig`` 会把既有 logger 置
    # ``disabled=True``（跨用例顺序依赖污染），monkeypatch 自动还原；**不削弱断言强度**。
    _logger = logging.getLogger("astra_application.services.audit_service")
    monkeypatch.setattr(_logger, "disabled", False)
    monkeypatch.setattr(_logger, "propagate", True)
    spool = AuditSpool(tmp_path / "spool")
    service = AuditService(sink=_BoomSink(), spool=spool)

    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        record = service.record(
            AuditRecordDTO(tenant_id="t-1", action="tool_call", request_id="req-fallback")
        )

    assert record.request_id == "req-fallback"  # 业务不被中断
    assert spool.pending_files(), "应已降级本地落盘"
    warnings = [
        r for r in caplog.records if r.levelno >= logging.WARNING  # type: ignore[attr-defined]
    ]
    assert warnings, "应产生告警日志"


def test_audit_total_failure_logs_error_and_counts(
    tmp_path: Path, caplog: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """③ 落盘也失败 → ERROR 日志（含 request_id/trace_id）+ 计数。"""
    # P2.7-B：显式隔离 logger（同 ②，防跨用例 ``disabled=True`` 污染）。
    _logger = logging.getLogger("astra_application.services.audit_service")
    monkeypatch.setattr(_logger, "disabled", False)
    monkeypatch.setattr(_logger, "propagate", True)
    metrics = _RecordingMetrics()
    service = AuditService(
        sink=_BoomSink(),
        spool=_BoomSpool(tmp_path / "spool"),
        metrics=metrics,
    )

    with caplog.at_level(logging.ERROR):  # type: ignore[attr-defined]
        service.record(
            AuditRecordDTO(
                tenant_id="t-1",
                action="tool_call",
                request_id="req-total-fail",
                trace_id="trace-123",
            )
        )

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]  # type: ignore[attr-defined]
    assert errors, "应产生 ERROR 级日志"
    assert any(getattr(r, "request_id", None) == "req-total-fail" for r in errors)
    assert (AUDIT_WRITE_FAILURE_TOTAL, 1) in metrics.calls


def test_audit_replay_is_idempotent(session_factory, tmp_path: Path) -> None:
    """④ 重放按 ``request_id`` 幂等去重：同键重复只入库一次。"""
    repository = SqlAuditRepository(session_factory)
    service = AuditService(repository=repository, spool=AuditSpool(tmp_path / "spool"))

    service.spool.write(AuditLog(tenant_id="t-1", action="login", request_id="dup-1"))
    service.spool.write(AuditLog(tenant_id="t-1", action="login", request_id="dup-1"))

    assert service.replay() == 1
    assert service.replay() == 0
    assert repository.exists_request_id("dup-1") is True
