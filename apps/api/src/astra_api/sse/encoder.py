"""领域事件 → SSE 帧编码器（W6 / T1-28；设计 §2.9；裁定 §2.1 / Q2）。

**纯字符串映射**：领域事件 ``type`` → SSE ``event:`` 通道名（静态字典），再编码为
``id:`` / ``event:`` / ``data:`` 三行 + 空行。

🔴 本模块**不 import** ``astra_event`` / ``sqlalchemy`` / ``astra_database``
   （`test_sse_encoder_has_no_domain_event_import` 强制）——编码器对事件**仅按
   ``type`` 字符串与 ``payload`` 值处理**，不绑定领域事件类。
"""

from __future__ import annotations

import json

__all__ = [
    "SSE_CHANNEL_BY_DOMAIN_TYPE",
    "channel_for",
    "encode_data_frame",
    "encode_heartbeat",
]

#: 领域事件 ``type`` → SSE ``event:`` 通道名（§2.1 逐条映射表）。
#: 未列入者 → **跳过**（不产帧，前端契约稳定）。
SSE_CHANNEL_BY_DOMAIN_TYPE: dict[str, str] = {
    "agent.started": "agent.started",
    "agent.thinking": "agent.thinking",
    "agent.message": "message.delta",
    "tool_call.started": "tool.started",
    "tool_call.completed": "tool.completed",
    "mcp_call.started": "mcp.started",
    "mcp_call.completed": "mcp.completed",
    "agent.completed": "agent.completed",
    "agent.failed": "agent.error",
    # Phase 2 · W3 / T2-16 新增通道（**仅追加**，不破坏既有 9 类契约；裁定 §6.2）
    "skill.resolved": "skill.resolved",
    "workflow.started": "workflow.started",
    "workflow.node.started": "workflow.node.started",
    "workflow.node.completed": "workflow.node.completed",
    "workflow.completed": "workflow.completed",
    "workflow.failed": "workflow.failed",
    "knowledge.indexed": "knowledge.indexed",
    "memory.written": "memory.written",
    "approval.requested": "approval.requested",
    "approval.decided": "approval.decided",
}


def channel_for(domain_type: str) -> str | None:
    """按领域 ``type`` 返回 SSE 通道名（未映射 → ``None``）。"""
    return SSE_CHANNEL_BY_DOMAIN_TYPE.get(domain_type)


def _project_payload(domain_type: str, payload: dict[str, object]) -> dict[str, object]:
    """按 §2.1 表投影 ``data:`` 载荷（``agent.message`` 的 ``content`` → ``delta``）。"""
    if domain_type == "agent.message":
        projected = {
            "run_id": payload.get("run_id"),
            "message_id": payload.get("message_id"),
            "role": payload.get("role"),
            "delta": payload.get("content"),
        }
        return {key: value for key, value in projected.items() if value is not None}
    return dict(payload)


def encode_data_frame(
    *,
    seq: int,
    domain_type: str,
    payload: dict[str, object],
) -> str | None:
    """编码一个 SSE 数据帧（``id:`` / ``event:`` / ``data:`` + 空行）。

    Args:
        seq: 帧 ``id:``（= ``agent_event.seq``，整数）。
        domain_type: 领域事件 ``type`` 字符串。
        payload: 事件载荷。

    Returns:
        编码后的帧字符串；``domain_type`` 未映射时返回 ``None``（跳过，不产帧）。
    """
    channel = channel_for(domain_type)
    if channel is None:
        return None
    data = json.dumps(
        _project_payload(domain_type, dict(payload)),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"id: {seq}\nevent: {channel}\ndata: {data}\n\n"


def encode_heartbeat(*, now_ms: int) -> str:
    """编码心跳注释帧（``: hb <unix_ms>`` + 空行；**不带** ``id:``）。

    不带 ``id:`` 以免污染 ``Last-Event-ID``（§2.2）。
    """
    return f": hb {now_ms}\n\n"
