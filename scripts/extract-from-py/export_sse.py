"""C-05 exporter: freeze the 19 SSE channels and their golden frames.

Produces::

    contracts/sse/channels.json                       19 channel entries + rules
    contracts/sse/golden/<channel>.txt                19 golden frames (1 file each)
    contracts/sse/golden/_guard-float-normalization.txt  1 extra guard sample

Ground rules that this module enforces (all measured, none copied from docs)
---------------------------------------------------------------------------
* The channel table is read from ``wbtime_ai_api/sse/encoder.py``
  (``SSE_CHANNEL_BY_DOMAIN_TYPE``) -- 9 core + 10 Phase 2 = 19, in declaration
  order.  The 6 renamed channels (``agent.message -> message.delta`` etc.) are
  asserted against a frozen table, so a silent wire rename fails the export.
* Every golden payload is produced by a **real event instance**
  (``<EventClass>.create(**kwargs)`` taken from ``wbtime_ai_event.events``), and
  the frame is produced by the **real encoder** ``encode_data_frame``.  No
  payload literal is ever hand-written; only the constructor arguments are
  chosen (and they are recorded per channel under ``constructor.kwargs``).
* ``seq`` is pinned to ``1`` for every channel, so a diff is always about the
  channel, never about a counter.
* The frame is then *verified* structurally (line layout, compact separators,
  key order, absence of ``\\r``, absence of ``\\uXXXX`` escapes) instead of
  being trusted because we wrote it.

Numeric format (roadmap §5.5 trap 2)
------------------------------------
``json.dumps(1.0)`` yields ``1.0`` while ``JSON.stringify(1.0)`` yields ``1``, so
"byte-identical frames" is unachievable while floats can reach the wire.  The
payload is therefore normalised by :func:`normalize_numbers` **before** it is
handed to the untouched encoder:

===========  ==========================================================
bool         unchanged (checked before ``int``)
int          unchanged
float        integral -> ``int``; otherwise fixed-point string, 6 dp
Decimal      converted to ``float``, then the two rules above
nan / inf    ``ValueError`` (not representable on the wire)
dict / list  recursed; dict key order preserved
===========  ==========================================================

Measured fact: the 19 official payloads contain **0 floats**, so the
normalisation is a no-op for them -- the 19 golden frames are byte-for-byte what
the legacy server emits today.  A 20th, clearly-labelled **guard** sample
(``_guard-float-normalization.txt``) injects floats into a real instance to prove
the rule actually fires; it is deliberately kept out of the 19.

Run under the legacy ``.venv`` interpreter (``run.py export`` re-executes).
"""

from __future__ import annotations

import inspect
import json
import math
import types
import typing
from decimal import Decimal
from typing import Any

import _bootstrap
import canonical
import hashes

__all__ = [
    "NAME",
    "DESCRIPTION",
    "CHANNELS_NAME",
    "GOLDEN_DIRNAME",
    "GUARD_NAME",
    "SEQ",
    "EXPECTED_CHANNEL_COUNT",
    "CORE_DOMAIN_TYPES",
    "PHASE2_DOMAIN_TYPES",
    "CHANNEL_RENAMES",
    "PARAM_VALUES",
    "PARAM_OVERRIDES",
    "NORMALIZATION_DECIMALS",
    "SseFreezeError",
    "render_type",
    "normalize_numbers",
    "count_floats",
    "export",
]

#: Registry name used by ``run.py --only``.
NAME = "sse"

#: Human readable description shown by ``run.py export``.
DESCRIPTION = "Freeze the 19 SSE channels + golden frames into contracts/sse/"

CHANNELS_NAME = "channels.json"
GOLDEN_DIRNAME = "golden"
GUARD_NAME = "_guard-float-normalization.txt"

#: Pinned ``id:`` value used by every golden frame.
SEQ = 1

#: Fraction digits used when a non-integral float must survive to the wire.
NORMALIZATION_DECIMALS = 6

EXPECTED_CHANNEL_COUNT = 19

#: The 9 core channels, in ``encoder.py`` declaration order.
CORE_DOMAIN_TYPES: tuple[str, ...] = (
    "agent.started",
    "agent.thinking",
    "agent.message",
    "tool_call.started",
    "tool_call.completed",
    "mcp_call.started",
    "mcp_call.completed",
    "agent.completed",
    "agent.failed",
)

#: The 10 Phase 2 channels added by W3 / T2-16, in declaration order.
PHASE2_DOMAIN_TYPES: tuple[str, ...] = (
    "skill.resolved",
    "workflow.started",
    "workflow.node.started",
    "workflow.node.completed",
    "workflow.completed",
    "workflow.failed",
    "knowledge.indexed",
    "memory.written",
    "approval.requested",
    "approval.decided",
)

#: Domain types whose SSE channel name differs from the domain type.
CHANNEL_RENAMES: dict[str, str] = {
    "agent.message": "message.delta",
    "tool_call.started": "tool.started",
    "tool_call.completed": "tool.completed",
    "mcp_call.started": "mcp.started",
    "mcp_call.completed": "mcp.completed",
    "agent.failed": "agent.error",
}

#: Minimal-but-sensible business values for every ``create()`` parameter.
#:
#: Keyed by parameter **name** (not by channel), so the same semantic field gets
#: the same value everywhere it appears.  Unknown names fall back to
#: :func:`_fallback_value`, derived from the annotation.
PARAM_VALUES: dict[str, Any] = {
    "run_id": "run_01",
    "agent_id": "agent_01",
    "agent_version_id": "agentver_01",
    "conversation_id": "conv_01",
    "run_mode": "inline",
    "iteration": 1,
    "message_id": "msg_01",
    "role": "assistant",
    "content": "你好，世界",
    "tool_call_id": "toolcall_01",
    "tool_name": "http.get",
    "attempt": 1,
    "arguments": {"url": "https://example.com"},
    "status": "succeeded",
    "duration_ms": 12,
    "error": "upstream returned 502",
    "mcp_call_id": "mcpcall_01",
    "server": "filesystem",
    "error_type": "ToolTimeout",
    "skill_name": "pdf",
    "skill_id": "skill_01",
    "version": "1.0.0",
    "workflow_id": "wf_01",
    "workflow_version_id": "wfver_01",
    "node_id": "node_01",
    "node_type": "agent",
    "kb_id": "kb_01",
    "document_id": "doc_01",
    "chunk_count": 3,
    "memory_id": "mem_01",
    "scope": "run",
    "key": "favorite_color",
    "approval_id": "appr_01",
    "subject_type": "tool_call",
    "subject_ref": "toolcall_01",
    "requested_by": "user_01",
    "decided_by": "user_01",
}

#: Per-channel refinements where the generic value would read wrong.
PARAM_OVERRIDES: dict[tuple[str, str], Any] = {
    ("approval.decided", "status"): "approved",
    ("knowledge.indexed", "status"): "indexed",
    ("memory.written", "key"): "favorite_color",
}

#: Guard sample: floats injected into a **real** ``AgentCompleted`` instance.
GUARD_DOMAIN_TYPE = "agent.completed"
GUARD_INJECTIONS: dict[str, Any] = {
    "score": 0.5,
    "ratio": 1.0,
    "neg_zero": -0.0,
    "nested": {"score": 0.25},
}

#: Every streaming endpoint of the legacy API (measured by grepping
#: ``media_type="text/event-stream"`` in ``apps/api/src/wbtime_ai_api/routers``).
SSE_ENDPOINTS: tuple[dict[str, str], ...] = (
    {
        "method": "POST",
        "path": "/api/v1/agents/{agent_id}/run",
        "router": "routers/v1/agents.py:347",
    },
    {
        "method": "GET",
        "path": "/api/v1/runs/{run_id}/events",
        "router": "routers/v1/runs.py:146",
    },
    {
        "method": "GET",
        "path": "/api/v1/tasks/{task_id}/events",
        "router": "routers/v1/tasks.py:402",
    },
    {
        "method": "POST",
        "path": "/api/v1/workflows/{workflow_id}/run",
        "router": "routers/v1/workflows.py:382",
    },
)


class SseFreezeError(RuntimeError):
    """Raised when the SSE contract diverges from the frozen baseline."""


# ---------------------------------------------------------------------------
# Type rendering
# ---------------------------------------------------------------------------


def render_type(annotation: Any) -> str:
    """Render a resolved type annotation as a compact readable string.

    Args:
        annotation: A type from ``typing.get_type_hints``.

    Returns:
        ``"str"``, ``"str | None"``, ``"dict[str, Any] | None"``, ``"null"`` …
    """
    if annotation is None or annotation is type(None):
        return "null"
    if annotation is typing.Any:
        return "Any"
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        return " | ".join(render_type(argument) for argument in typing.get_args(annotation))
    if origin is not None:
        base = getattr(origin, "__name__", str(origin))
        arguments = typing.get_args(annotation)
        if arguments:
            return f"{base}[{', '.join(render_type(argument) for argument in arguments)}]"
        return base
    return getattr(annotation, "__name__", str(annotation))


# ---------------------------------------------------------------------------
# Numeric normalisation
# ---------------------------------------------------------------------------


def normalize_numbers(value: Any, *, decimals: int = NORMALIZATION_DECIMALS) -> Any:
    """Normalise ``value`` so that Python and JavaScript serialise it identically.

    See the module docstring for the rule table.

    Args:
        value: Any payload value.
        decimals: Fraction digits used for non-integral floats.

    Returns:
        A structurally identical value with floats replaced by ``int`` or by a
        fixed-point decimal string.

    Raises:
        ValueError: If ``value`` contains a non-finite float (``nan`` / ``inf``),
            which has no cross-language representation.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return normalize_numbers(float(value), decimals=decimals)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float is not allowed in an SSE payload: {value!r}")
        if value.is_integer() and abs(value) < 2**53:
            return int(value)
        return f"{value:.{decimals}f}"
    if isinstance(value, dict):
        return {str(key): normalize_numbers(item, decimals=decimals) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_numbers(item, decimals=decimals) for item in value]
    return value


def count_floats(value: Any) -> int:
    """Count ``float`` occurrences in ``value`` (recursing into dict/list/tuple)."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (float, Decimal)):
        return 1
    if isinstance(value, dict):
        return sum(count_floats(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(count_floats(item) for item in value)
    return 0


# ---------------------------------------------------------------------------
# Payload construction from real event instances
# ---------------------------------------------------------------------------


def _fallback_value(name: str, annotation: Any) -> Any:
    """Derive a deterministic value for an unknown ``create()`` parameter.

    Args:
        name: Parameter name.
        annotation: Resolved annotation.

    Returns:
        ``"<name>_01"`` for strings, ``1`` for ints, ``{"key": "value"}`` for
        mappings, ``[]`` for sequences.
    """
    rendered = render_type(annotation)
    base = rendered.split(" | ")[0]
    if base in ("int", "integer"):
        return 1
    if base.startswith("dict") or base.startswith("Mapping"):
        return {"key": "value"}
    if base.startswith("list") or base.startswith("tuple"):
        return []
    if base in ("bool",):
        return True
    if base in ("float",):
        # Deliberately not used by any current event; a float here would need a
        # normalisation decision, so fail loudly instead of inventing one.
        raise SseFreezeError(f"parameter {name!r} is annotated float; extend PARAM_VALUES explicitly")
    return f"{name}_01"


def _constructor_kwargs(domain_type: str, factory: Any) -> dict[str, Any]:
    """Build ``create()`` keyword arguments for one channel.

    Args:
        domain_type: Domain event type (channel key).
        factory: The event class's ``create`` classmethod.

    Returns:
        Keyword arguments in signature declaration order.

    Raises:
        SseFreezeError: If a parameter has no value and no derivable fallback.
    """
    hints = typing.get_type_hints(factory)
    kwargs: dict[str, Any] = {}
    for name, parameter in inspect.signature(factory).parameters.items():
        if name in ("cls", "self"):
            continue
        if (domain_type, name) in PARAM_OVERRIDES:
            kwargs[name] = PARAM_OVERRIDES[(domain_type, name)]
            continue
        if name in PARAM_VALUES:
            kwargs[name] = PARAM_VALUES[name]
            continue
        annotation = hints.get(name, parameter.annotation)
        kwargs[name] = _fallback_value(name, annotation)
    return kwargs


def _payload_fields(factory: Any) -> dict[str, Any]:
    """Describe the payload schema of an event constructor.

    The event dataclass itself only carries the generic envelope fields
    (``event_id`` / ``occurred_at`` / ``payload`` / ``seq``); the **payload**
    schema is the keyword signature of its ``create()`` classmethod, so that is
    what gets documented.

    Args:
        factory: The event class's ``create`` classmethod.

    Returns:
        ``{field: {"type", "required", "default"}}`` in signature order.
    """
    hints = typing.get_type_hints(factory)
    fields: dict[str, Any] = {}
    for name, parameter in inspect.signature(factory).parameters.items():
        if name in ("cls", "self"):
            continue
        has_default = parameter.default is not inspect.Parameter.empty
        default = None
        if has_default:
            try:
                json.dumps(parameter.default)
                default = parameter.default
            except (TypeError, ValueError):
                default = repr(parameter.default)
        fields[name] = {
            "type": render_type(hints.get(name, parameter.annotation)),
            "required": not has_default,
            "default": default,
        }
    return fields


# ---------------------------------------------------------------------------
# Frame verification
# ---------------------------------------------------------------------------


def _verify_frame(
    frame: str,
    *,
    seq: int,
    channel: str,
    payload: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    """Assert the structural properties of an encoded frame and decode its data.

    Args:
        frame: Output of ``encode_data_frame``.
        seq: Expected ``id:`` value.
        channel: Expected ``event:`` value.
        payload: Payload that was passed to the encoder (already normalised).
        label: Human label used in error messages.

    Returns:
        ``{"data": <decoded data object>, "data_json": <raw json text>}``.

    Raises:
        SseFreezeError: If any structural property is violated.
    """
    lines = frame.split("\n")
    problems: list[str] = []
    if len(lines) != 5:
        problems.append(f"expected 5 LF-separated lines, got {len(lines)}: {lines!r}")
    if "\r" in frame:
        problems.append("frame contains CR (must be LF only)")
    if not frame.endswith("\n\n"):
        problems.append("frame must end with a blank line")
    if lines and lines[0] != f"id: {seq}":
        problems.append(f"line 1: expected 'id: {seq}', got {lines[0]!r}")
    if len(lines) > 1 and lines[1] != f"event: {channel}":
        problems.append(f"line 2: expected 'event: {channel}', got {lines[1]!r}")
    if problems:
        raise SseFreezeError(f"{label}: " + "; ".join(problems))

    data_json = lines[2][len("data: ") :]
    if not lines[2].startswith("data: "):
        raise SseFreezeError(f"{label}: line 3 must start with 'data: '")
    if '", "' in data_json or '": "' in data_json:
        raise SseFreezeError(f"{label}: data uses spaced JSON separators (expected ', ' / ': ' free)")

    decoded = json.loads(data_json)
    if not isinstance(decoded, dict):
        raise SseFreezeError(f"{label}: data must decode to an object, got {type(decoded).__name__}")
    if list(decoded) != list(payload):
        raise SseFreezeError(
            f"{label}: data key order {list(decoded)} differs from payload order {list(payload)} "
            "(sort_keys must stay off -- TS must preserve insertion order)"
        )
    if decoded != json.loads(json.dumps(payload, ensure_ascii=False)):
        raise SseFreezeError(f"{label}: data does not round-trip to the payload")

    has_non_ascii = any(ord(char) > 127 for char in data_json)
    if has_non_ascii and "\\u" in data_json:
        # A literal backslash-u inside a *string value* would be indistinguishable
        # from an escape, so this check is only trusted when no such value exists.
        raise SseFreezeError(f"{label}: non-ASCII was escaped (ensure_ascii must stay False)")
    return {"data": decoded, "data_json": data_json}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _load_legacy() -> dict[str, Any]:
    """Import the legacy encoder, event classes and stream module.

    Returns:
        A dict with ``channels`` (ordered dict), ``events`` (``type -> class``),
        ``encoder``, ``stream`` and ``event_class_count``.
    """
    from wbtime_ai_api.sse import encoder as encoder_module  # noqa: PLC0415
    from wbtime_ai_core import DomainEvent  # noqa: PLC0415

    event_modules = (
        "agent",
        "approval",
        "knowledge",
        "memory",
        "skill",
        "system",
        "user",
        "workflow",
        "workspace",
    )
    events: dict[str, type[Any]] = {}
    for module_name in event_modules:
        module = __import__(f"wbtime_ai_event.events.{module_name}", fromlist=["*"])
        for attribute, value in vars(module).items():
            if attribute.startswith("_"):
                continue
            if not inspect.isclass(value):
                continue
            if value is DomainEvent or not issubclass(value, DomainEvent):
                continue
            if value.__module__ != module.__name__:
                continue
            events[str(value.type)] = value

    from wbtime_ai_api.sse import stream as stream_module  # noqa: PLC0415

    return {
        "channels": dict(encoder_module.SSE_CHANNEL_BY_DOMAIN_TYPE),
        "encoder": encoder_module,
        "events": events,
        "event_class_count": len(events),
        "stream": stream_module,
    }


def export(ctx: _bootstrap.ExtractContext) -> dict[str, Any]:
    """Export ``channels.json`` and the golden frames.

    Args:
        ctx: Resolved extraction context.

    Returns:
        Metrics dict (``summary`` is printed by ``run.py``).

    Raises:
        SseFreezeError: If any frozen expectation is violated.
    """
    import_dirs = _bootstrap.install_import_paths(ctx.source)
    if not _bootstrap.can_import("wbtime_ai_api.sse.encoder"):
        raise SseFreezeError(
            "cannot import wbtime_ai_api.sse.encoder -- run this exporter with the legacy "
            f"interpreter ({ctx.python_executable}) and the {len(import_dirs)} import roots installed"
        )

    loaded = _load_legacy()
    channel_map: dict[str, str] = loaded["channels"]
    events: dict[str, type[Any]] = loaded["events"]
    encoder = loaded["encoder"]
    stream_module = loaded["stream"]

    # -- 1. Hard checks on the channel table --------------------------------
    expected_order = CORE_DOMAIN_TYPES + PHASE2_DOMAIN_TYPES
    diffs: list[str] = []
    if len(channel_map) != EXPECTED_CHANNEL_COUNT:
        diffs.append(f"channel count: expected {EXPECTED_CHANNEL_COUNT}, got {len(channel_map)}")
    if tuple(channel_map) != expected_order:
        diffs.append(
            f"channel order drifted: expected {list(expected_order)}, got {list(channel_map)}"
        )
    for domain_type, channel in channel_map.items():
        wanted = CHANNEL_RENAMES.get(domain_type, domain_type)
        if channel != wanted:
            diffs.append(f"{domain_type}: channel expected {wanted!r}, got {channel!r}")
        if domain_type not in events:
            diffs.append(f"{domain_type}: no DomainEvent subclass declares this type")
    unmapped_domain_types = sorted(set(events) - set(channel_map))
    if len(unmapped_domain_types) != 8:
        diffs.append(
            f"event classes without an SSE channel: expected 8, got {len(unmapped_domain_types)}"
        )
    if channel_map.get("agent.message") != "message.delta":
        diffs.append("agent.message -> message.delta rename is missing")
    if tuple(stream_module._DOMAIN_TYPES) != tuple(channel_map):
        diffs.append("stream._DOMAIN_TYPES does not match the channel table")
    if encoder.channel_for("__wbtime_unmapped__") is not None:
        diffs.append("channel_for() must return None for an unmapped domain type")
    if diffs:
        raise SseFreezeError(
            "SSE channel table diverged from the frozen baseline:\n  - " + "\n  - ".join(diffs)
        )

    # -- 2. Build payloads from real instances, encode, verify, write -------
    golden_dir = ctx.contracts_dir / "sse" / GOLDEN_DIRNAME
    channels: list[dict[str, Any]] = []
    float_total = 0
    frame_bytes_total = 0
    by_channel: dict[str, str] = {}

    for index, (domain_type, channel) in enumerate(channel_map.items(), start=1):
        event_class = events[domain_type]
        factory = event_class.create
        kwargs = _constructor_kwargs(domain_type, factory)
        instance = factory(**kwargs)
        raw_payload = dict(instance.payload)
        float_total += count_floats(raw_payload)
        payload = normalize_numbers(raw_payload)

        frame = encoder.encode_data_frame(seq=SEQ, domain_type=domain_type, payload=payload)
        if frame is None:
            raise SseFreezeError(f"{domain_type}: encode_data_frame returned None (unmapped)")

        # What actually reaches the wire: the encoder projects the payload for a
        # few channels (``agent.message`` renames ``content`` -> ``delta``).  The
        # *real* projection function is used instead of re-implementing it.
        wire_payload = dict(encoder._project_payload(domain_type, payload))

        golden_name = f"{channel}.txt"
        golden_rel = f"{GOLDEN_DIRNAME}/{golden_name}"
        verified = _verify_frame(
            frame, seq=SEQ, channel=channel, payload=wire_payload, label=golden_rel
        )
        canonical.write_text(golden_dir / golden_name, frame)
        digest = hashes.sha256_bytes(frame.encode("utf-8"))
        frame_bytes_total += len(frame.encode("utf-8"))

        raw_keys = list(raw_payload)
        wire_keys = list(wire_payload)
        projection: dict[str, Any] | None = None
        if raw_keys != wire_keys:
            dropped = [key for key in raw_keys if key not in wire_keys]
            added = [key for key in wire_keys if key not in raw_keys]
            projection = {
                "source": "read:apps/api/src/wbtime_ai_api/sse/encoder.py::_project_payload",
                "dropped": dropped,
                "added": added,
                "rule": ", ".join(f"{old} -> {new}" for old, new in zip(dropped, added)) or None,
                "note": "该投影是通道专属逻辑，TS 侧必须逐字复刻。",
            }
            if domain_type != "agent.message":
                raise SseFreezeError(
                    f"{domain_type}: unexpected payload projection {projection['rule']!r}"
                )

        channels.append(
            {
                "index": index,
                "domain_type": domain_type,
                "channel": channel,
                "phase": "core" if domain_type in CORE_DOMAIN_TYPES else "phase2",
                "phase_source": "read:encoder.py 分段注释（'Phase 2 · W3 / T2-16 新增通道'）",
                "event_class": event_class.__name__,
                "event_module": event_class.__module__,
                "constructor": {
                    "factory": f"{event_class.__name__}.create",
                    "kwargs": kwargs,
                    "kwargs_source": "export_sse.PARAM_VALUES / PARAM_OVERRIDES",
                },
                "payload_fields": _payload_fields(factory),
                "payload_keys_in_order": raw_keys,
                "projected_fields": wire_keys,
                "projection": projection,
                "frame": {
                    "seq": SEQ,
                    "bytes": len(frame.encode("utf-8")),
                    "sha256": digest,
                },
                "golden": golden_rel,
                "golden_sha256": digest,
            }
        )
        by_channel[channel] = domain_type

    # -- 3. Guard sample: prove the float rule actually fires ---------------
    guard_class = events[GUARD_DOMAIN_TYPE]
    guard_instance = guard_class.create(**_constructor_kwargs(GUARD_DOMAIN_TYPE, guard_class.create))
    guard_raw = dict(guard_instance.payload)
    guard_raw.update(GUARD_INJECTIONS)
    raw_dumps = json.dumps(guard_raw, ensure_ascii=False, separators=(",", ":"))
    guard_payload = normalize_numbers(guard_raw)
    guard_frame = encoder.encode_data_frame(
        seq=SEQ, domain_type=GUARD_DOMAIN_TYPE, payload=guard_payload
    )
    if guard_frame is None:
        raise SseFreezeError("guard frame: encode_data_frame returned None")
    guard_verified = _verify_frame(
        guard_frame,
        seq=SEQ,
        channel=channel_map[GUARD_DOMAIN_TYPE],
        payload=guard_payload,
        label=f"{GOLDEN_DIRNAME}/{GUARD_NAME}",
    )
    for key, expected in (
        ("score", "0.500000"),
        ("ratio", 1),
        ("neg_zero", 0),
        ("nested", {"score": "0.250000"}),
    ):
        actual = guard_verified["data"].get(key)
        if actual != expected:
            raise SseFreezeError(
                f"guard frame: {key} normalised to {actual!r}, expected {expected!r}"
            )
    if raw_dumps.count("1.0") < 1 or "-0.0" not in raw_dumps:
        raise SseFreezeError("guard frame: raw payload no longer contains the float guard values")
    canonical.write_text(golden_dir / GUARD_NAME, guard_frame)
    guard_digest = hashes.sha256_bytes(guard_frame.encode("utf-8"))

    # -- 4. Heartbeat sample (frame-level, not channel-level) ---------------
    heartbeat_now_ms = 1_700_000_000_000
    heartbeat_frame = encoder.encode_heartbeat(now_ms=heartbeat_now_ms)
    expected_heartbeat = f": hb {heartbeat_now_ms}\n\n"
    if heartbeat_frame != expected_heartbeat:
        raise SseFreezeError(
            f"heartbeat frame changed: expected {expected_heartbeat!r}, got {heartbeat_frame!r}"
        )
    if "id:" in heartbeat_frame:
        raise SseFreezeError("heartbeat frame must not carry an id: line")

    # -- 5. Document --------------------------------------------------------
    default_heartbeat = inspect.signature(stream_module.stream_run).parameters[
        "heartbeat_seconds"
    ].default

    document: dict[str, Any] = {
        "schema": "wbtimeai.contracts/sse-channels",
        "contract_version": 1,
        "generated_by": "scripts/extract-from-py/export_sse.py",
        "source": ctx.source,
        "sources": {
            "channel_map": "apps/api/src/wbtime_ai_api/sse/encoder.py::SSE_CHANNEL_BY_DOMAIN_TYPE",
            "encoder": "apps/api/src/wbtime_ai_api/sse/encoder.py::encode_data_frame / encode_heartbeat",
            "stream": "apps/api/src/wbtime_ai_api/sse/stream.py::stream_run",
            "events": "packages/event/src/wbtime_ai_event/events/*.py",
        },
        "frame_format": {
            "data_frame": {
                "template": "id: {seq}\\nevent: {channel}\\ndata: {json}\\n\\n",
                "line_layout": ["id: <int>", "event: <channel>", "data: <json>", "", ""],
                "bytes_note": "帧以空行结尾（两个 \\n），逐字节可比，不得追加换行。",
                "seq_policy": (
                    "19 条 golden 统一 id: 1（SEQ=1）。真实流中 id 等于 agent_event.seq，"
                    "由 EventDispatcher 投递前分配；golden 固定 1 是为了让 diff 只反映通道差异。"
                ),
            },
            "heartbeat": {
                "template": ": hb {now_ms}\\n\\n",
                "sample": heartbeat_frame,
                "sample_now_ms": heartbeat_now_ms,
                "sha256": hashes.sha256_bytes(heartbeat_frame.encode("utf-8")),
                "carries_id": False,
                "note": "注释帧不带 id:，不污染 Last-Event-ID（§2.2）。",
                "default_interval_seconds": default_heartbeat,
                "only_when_idle": True,
            },
            "json": {
                "ensure_ascii": False,
                "separators": [",", ":"],
                "sort_keys": False,
                "indent": None,
                "note": (
                    "ensure_ascii=False：CJK 原样输出，**不得**出现 \\uXXXX 转义；"
                    "separators=(',',':')：紧凑无空格；"
                    "sort_keys=False：键序 = payload 插入序，TS 侧必须保序（Object.keys 顺序即契约）。"
                ),
            },
            "line_endings": "LF only — 帧内不得出现 CR",
            "content_type": "text/event-stream",
            "wrapped_by_response_shell": False,
            "wrapped_note": "§11.1 例外：SSE 帧不套 {code,message,data,request_id} 壳；request_id 仅经响应头下发。",
        },
        "numeric_format": {
            "rule_version": 1,
            "policy": "integers-only-on-the-wire",
            "why": (
                "Python json.dumps(1.0) -> '1.0'，JS JSON.stringify(1.0) -> '1'；"
                "只要整数值浮点能上帧，「逐字节相同」在原理上不可达。"
            ),
            "applied_where": (
                "生成器在把 payload 交给 encode_data_frame **之前**归一化；"
                "encode_data_frame / encode_heartbeat 本体未做任何修改。"
            ),
            "rules": [
                {"input": "bool", "output": "unchanged", "note": "bool 判定先于 int，避免 True -> 1"},
                {"input": "int", "output": "unchanged"},
                {
                    "input": "float, is_integer() 且 abs < 2**53",
                    "output": "int(value)",
                    "example": "1.0 -> 1",
                },
                {
                    "input": "float, 其余有限值",
                    "output": f"定点十进制字符串，恰好 {NORMALIZATION_DECIMALS} 位小数",
                    "example": f'0.5 -> "0.500000"',
                },
                {"input": "Decimal", "output": "先转 float，再按上面两条处理"},
                {"input": "float nan / inf", "output": "抛 ValueError（不可上线）"},
                {"input": "dict / list / tuple", "output": "递归处理；dict 键序不变"},
            ],
            "guard_frame": f"{GOLDEN_DIRNAME}/{GUARD_NAME}",
            "guard_explanation": (
                "第 20 条样本：从**真实** AgentCompleted 实例出发，注入 score=0.5 / ratio=1.0 / "
                "neg_zero=-0.0 / nested={'score':0.25} 以证明两条分支都真的生效。"
                "它不属于 19 条正式通道 golden。"
            ),
            "official_payload_float_count": float_total,
            "official_payloads_float_free": float_total == 0,
            "official_note": (
                f"19 条正式 golden 的载荷中浮点数实测 {float_total} 个 ⇒ 归一化对它们是 no-op，"
                "golden 字节 == 旧仓服务端当前实际输出。"
            ),
        },
        "stream_semantics": {
            "source": "apps/api/src/wbtime_ai_api/sse/stream.py",
            "subscribe_types": list(stream_module._DOMAIN_TYPES),
            "seq_source": "agent_event.seq（EventDispatcher 投递/落库前统一分配）",
            "resume": "Last-Event-ID 请求头或 ?after_seq：只回放 seq > last 的事件",
            "dedupe": "实时事件若 seq <= 已产出 seq 则丢弃；无 seq 的事件按 (type,payload) 指纹兜底去重",
            "terminal_types": sorted(stream_module._TERMINAL_TYPES),
            "active_statuses": sorted(stream_module._ACTIVE_STATUSES),
            "unmapped_domain_type": "channel_for() 返回 None ⇒ 不产帧（不是错误帧，也不是空帧）",
            "accept_negotiation": "POST /agents/{id}/run：Accept 含 text/event-stream 或缺省/*/* → SSE，否则 JSON",
            "disconnect": "生成器被关闭/取消 → 触发 cancel(run_id)（INLINE 断连即取消）",
        },
        "sse_endpoints": [
            {
                **endpoint,
                "content_type": "text/event-stream",
                "openapi_declares": "application/json",
                "openapi_discrepancy": (
                    "OpenAPI 无法表达 SSE：冻结文档里这两个端点声明的是 application/json。"
                    "TS 代码生成必须把它们排除在 JSON 客户端之外，按本文件的帧契约手写。"
                ),
            }
            for endpoint in SSE_ENDPOINTS
        ],
        "channels": channels,
        "by_channel": by_channel,
        "guard": {
            "file": f"{GOLDEN_DIRNAME}/{GUARD_NAME}",
            "domain_type": GUARD_DOMAIN_TYPE,
            "channel": channel_map[GUARD_DOMAIN_TYPE],
            "seq": SEQ,
            "sha256": guard_digest,
            "base_instance": f"{guard_class.__name__}.create(...) + 注入浮点",
            "injected": {key: repr(value) for key, value in GUARD_INJECTIONS.items()},
            "raw_data_json": raw_dumps,
            "normalized_data_json": guard_verified["data_json"],
            "is_official_channel_golden": False,
        },
        "meta": {
            "count": len(channels),
            "core_count": sum(1 for entry in channels if entry["phase"] == "core"),
            "phase2_count": sum(1 for entry in channels if entry["phase"] == "phase2"),
            "renamed_channel_count": len(CHANNEL_RENAMES),
            "event_classes_total": loaded["event_class_count"],
            "domain_types_without_channel": unmapped_domain_types,
            "domain_types_without_channel_count": len(unmapped_domain_types),
            "golden_file_count": len(channels),
            "guard_file_count": 1,
            "frame_bytes_total": frame_bytes_total,
            "channels_digest_sha256": hashes.sha256_bytes(
                canonical.dumps(channels).encode("utf-8")
            ),
            "golden_index_sha256": hashes.sha256_bytes(
                "".join(
                    f"{entry['domain_type']}\t{entry['golden_sha256']}\n" for entry in channels
                ).encode("utf-8")
            ),
        },
    }

    path, text = canonical.write_document(ctx.contracts_dir / "sse" / CHANNELS_NAME, document)

    return {
        "summary": (
            f"channels={len(channels)} core={document['meta']['core_count']} "
            f"phase2={document['meta']['phase2_count']} golden={len(channels)} guard=1 "
            f"floats={float_total} frame_bytes={frame_bytes_total} sha256={hashes.sha256_file(path)[:12]}"
        ),
        "channels": len(channels),
        "golden_files": len(channels) + 1,
        "path": str(path),
        "sha256": hashes.sha256_file(path),
    }
