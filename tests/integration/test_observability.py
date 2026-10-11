"""可观测骨架集成测试（T1-04 / 设计 §2.7.3 / 总纲 §11.1）。

覆盖：
- 每次响应带 ``X-Request-Id``（UUIDv7）与 ``X-Trace-Id``；客户端传入则回显；
- **成功 / 失败响应体均含 ``request_id`` 且 == 响应头 ``X-Request-Id``**（总纲 §11.1）；
- 日志上下文（``trace_id`` / ``span_id``）注入每条日志记录（``caplog`` 断言）；
- 首批 5 个 Metrics 计数器可注册（``build_metrics``）；
- ``observability.metrics_enabled`` 默认 ``false`` → ``/metrics`` 404；开启 → 200。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from astra_logging import (
    DEFAULT_COUNTER_NAMES,
    RUN_TOTAL,
    bind_context,
    build_metrics,
    install_log_context_factory,
)
from fastapi.testclient import TestClient

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_responses_carry_request_and_trace_headers(client: Any) -> None:
    """/health 响应带 X-Request-Id（UUIDv7）/ X-Trace-Id。"""
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    trace_id = response.headers.get("X-Trace-Id")
    assert request_id and _UUID_RE.match(request_id), f"X-Request-Id 非 UUIDv7：{request_id}"
    assert trace_id and _UUID_RE.match(trace_id), f"X-Trace-Id 非 UUIDv7：{trace_id}"


def test_request_id_is_echoed_when_supplied(client: Any) -> None:
    """客户端传入 X-Request-Id / X-Trace-Id 时原样回显（便于跨系统串联）。"""
    supplied = "0192f0f0-0000-7000-8000-000000000000"
    response = client.get(
        "/health",
        headers={"X-Request-Id": supplied, "X-Trace-Id": supplied},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == supplied
    assert response.headers["X-Trace-Id"] == supplied


def test_headers_present_on_error_response(client: Any) -> None:
    """错误响应（404）同样带 X-Request-Id / X-Trace-Id。"""
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert _UUID_RE.match(response.headers["X-Request-Id"])
    assert _UUID_RE.match(response.headers["X-Trace-Id"])


def test_success_body_request_id_matches_header(client: Any) -> None:
    """成功响应壳 ``request_id`` == 响应头 ``X-Request-Id``（同源 UUIDv7，§11.1）。"""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"code", "message", "data", "request_id"}
    assert body["code"] == 0 and body["message"] == "ok"
    request_id = body["request_id"]
    assert request_id and _UUID_RE.match(request_id)
    assert request_id == response.headers["X-Request-Id"]


def test_success_request_id_echoes_supplied_header(client: Any) -> None:
    """客户端传入 X-Request-Id（非 UUIDv7 亦可）→ 响应体/头一致回显。"""
    supplied = "trace-abc-123"
    response = client.get("/health", headers={"X-Request-Id": supplied})
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == supplied
    assert response.json()["request_id"] == supplied


def test_error_body_request_id_matches_header(client: Any) -> None:
    """失败响应壳 ``request_id`` == 响应头 ``X-Request-Id``（§11.1）。"""
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-Id"]
    assert _UUID_RE.match(body["request_id"])


def test_log_records_carry_trace_context(client: Any, caplog: logging.LogCaptureFixture) -> None:
    """结构化日志携带 trace_id / span_id 上下文（LogRecord 注入）。"""
    install_log_context_factory()  # 幂等，确保夹具未触发时也生效

    with caplog.at_level(logging.INFO, logger="astra.test.observability"):
        with bind_context(request_id="req-1", trace_id="trace-1", span_id="span-1", run_id="run-1"):
            logging.getLogger("astra.test.observability").info("hello-context")

    records = [r for r in caplog.records if r.message == "hello-context"]
    assert records, "未捕获到日志记录"
    record = records[-1]
    assert getattr(record, "request_id", None) == "req-1"
    assert getattr(record, "trace_id", None) == "trace-1"
    assert getattr(record, "span_id", None) == "span-1"
    assert getattr(record, "run_id", None) == "run-1"


def test_build_metrics_registers_five_counters() -> None:
    """首批 5 个计数器可注册并可累加。"""
    metrics = build_metrics(enabled=True)
    snapshot = metrics.snapshot()  # type: ignore[attr-defined]
    for name in DEFAULT_COUNTER_NAMES:
        assert name in snapshot, f"缺少计数器：{name}"

    metrics.counter(RUN_TOTAL, 1, status="success")
    assert metrics.value(RUN_TOTAL, status="success") == 1  # type: ignore[attr-defined]


def test_metrics_disabled_by_default_returns_404(client: Any) -> None:
    """社区默认关闭 → /metrics 未挂载（404）。"""
    response = client.get("/metrics")
    assert response.status_code == 404


def test_metrics_enabled_exposes_endpoint(isolated_settings_env: Any, monkeypatch) -> None:
    """开启 observability.metrics_enabled → /metrics 可访问并含计数器名。"""
    from astra_config.loader import reset_settings_cache

    monkeypatch.setenv("ASTRA_OBSERVABILITY__METRICS_ENABLED", "true")
    reset_settings_cache()

    from astra_api.main import create_app

    application = create_app()
    with TestClient(application) as test_client:
        response = test_client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    for name in DEFAULT_COUNTER_NAMES:
        assert name in body, f"/metrics 未包含计数器：{name}"
