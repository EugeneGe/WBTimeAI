"""O-C 降级档：外部 oracle 冻结快照的读写 + ``DEGRADED`` 标记（V0.0.2 · T03）。

设计依据：施工 ``README.md`` §1.3（外部 oracle 三档）与 §5-T03（产出物 / 要点）。

档位口径（**不得混用**）：

======================  ====================================================
档                       强度 / 用途
======================  ====================================================
O-A ``--oracle legacy``  强：真值来自 ``_old`` 源码树（不在本仓）
O-B 活体后端              强但只覆盖 openapi / DDL-sqlite 两面（不属本脚本）
O-C ``--oracle snapshot`` 弱：快照仍是**可改文件**，只防「忘记更新」，
                          不防「蓄意同改」⇒ 调用方必须打印 ``DEGRADED``
======================  ====================================================

**落盘位置硬约束**：快照只能落 ``docs/V1.0/V0.0.2-oracle自证与假绿反例/03-台账/``，
**绝不落 ``contracts/``**（那会同时污染被验对象与真值 ⇒ 自证失效）。本模块在写入前
显式断言这一点，违反即 :class:`SnapshotError`（不可降级为警告）。

``--write-snapshot`` 只允许在 **O-A 扫描成功** 后执行——由调用方
（``scripts/oracle_recompute.py``）保证；本模块额外要求 ``facts`` 非空（空快照 = 假值）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final, Sequence

sys.dont_write_bytecode = True

# 允许以 ``python -B scripts/oracle/snapshot.py`` 与 ``import oracle.snapshot`` 两种方式加载。
_SCRIPTS_DIR: Final[Path] = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:  # pragma: no cover - depends on invocation style
    sys.path.insert(0, str(_SCRIPTS_DIR))

from oracle.legacy_scan import (  # noqa: E402  (sys.path 先调整再导入)
    LegacyFacts,
    LegacyOracle,
    OracleUnavailable,
    ReadonlyViolation,
    _utc_now_iso,
)

#: 快照文件格式标识（读到别的格式 ⇒ 视为不可用，不猜字段）。
SNAPSHOT_SCHEMA: Final[str] = "wbtimeai.oracle-snapshot/v1"

#: 降级档标记（调用方必须原样打印；**禁止**在降级档打印 PASS）。
DEGRADED_MARKER: Final[str] = "DEGRADED"

#: 默认快照位置（相对仓根）。只允许落在 ``docs/`` 的台账目录。
DEFAULT_SNAPSHOT_RELATIVE: Final[str] = (
    "docs/V1.0/V0.0.2-oracle自证与假绿反例/03-台账/oracle-snapshot.json"
)

#: 快照档的档位标签（写进 payload，读者一眼看出它不是真值）。
ORACLE_TIER_SNAPSHOT: Final[str] = "O-C(snapshot)"


class SnapshotError(RuntimeError):
    """Raised when a snapshot write/read would violate a hard rule.

    Two cases: target path inside ``contracts/`` (forbidden) and payload shape
    mismatch (cannot be trusted). Callers map it to ``21`` / ``22``.
    """


def default_snapshot_path(repo_root: Path) -> Path:
    """Return the canonical snapshot path under ``docs/``.

    Args:
        repo_root: Repository root.

    Returns:
        ``<repo_root>/docs/V1.0/V0.0.2-.../03-台账/oracle-snapshot.json``.
    """
    return Path(repo_root).resolve() / DEFAULT_SNAPSHOT_RELATIVE


def assert_writable_target(path: Path, contracts_dir: Path) -> Path:
    """Assert the snapshot is **not** written inside ``contracts/``.

    Args:
        path: Intended snapshot path.
        contracts_dir: Frozen contract directory (must stay read-only).

    Returns:
        The resolved path.

    Raises:
        SnapshotError: If ``path`` resolves inside ``contracts_dir``.
    """
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(Path(contracts_dir).expanduser().resolve())
    except ValueError:
        return resolved
    raise SnapshotError(
        f"refusing to write snapshot inside contracts/: {resolved} "
        "(快照落 contracts/ 会同时污染被验对象与真值)"
    )


def write_snapshot(
    facts: LegacyFacts, path: Path, *, contracts_dir: Path, oracle_tier: str = "O-A"
) -> dict[str, Any]:
    """Write ``facts`` as a frozen O-C snapshot.

    Args:
        facts: Facts produced by a **successful** O-A scan.
        path: Destination (must stay outside ``contracts/``).
        contracts_dir: Frozen contract directory (guard only).
        oracle_tier: Which tier produced the payload.

    Returns:
        The written payload (also useful for logging).

    Raises:
        SnapshotError: If the target is inside ``contracts/`` or the facts are
            empty (an empty snapshot is a fake value, not a degraded oracle).
    """
    if not facts.openapi_paths or not facts.ddl_tables or not facts.sse_channels:
        raise SnapshotError(
            "refusing to write an empty snapshot (no face recomputed => fake truth)"
        )
    destination = assert_writable_target(path, contracts_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "oracle_tier": oracle_tier,
        "generated_at": _utc_now_iso(),
        "generated_by": "scripts/oracle/snapshot.py --write-snapshot",
        "degraded": True,
        "degraded_note": (
            "O-C 快照仍是仓内可改文件：只防「忘记更新」，不防「蓄意同改」；"
            "consumer 必须打印 DEGRADED，且不得表述为「与外部真值一致」"
        ),
        "sha256_scope": "sha256 由台账 md 钉住（docs/ 独立仓，CI 不可改 contracts/）",
        "facts": facts.to_dict(),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    destination.write_text(text, encoding="utf-8")
    return payload


def read_snapshot(path: Path) -> tuple[LegacyFacts, dict[str, Any]]:
    """Read and validate a frozen snapshot.

    Args:
        path: Snapshot path.

    Returns:
        ``(facts, payload_without_facts)``.

    Raises:
        OracleUnavailable: If the file is missing, unparsable, of another schema,
            or structurally incomplete — an unreadable snapshot is *unavailable*,
            never an empty truth.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise OracleUnavailable(f"snapshot not found: {candidate}")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OracleUnavailable(f"snapshot unreadable: {candidate} ({exc})") from exc
    if not isinstance(payload, dict):
        raise OracleUnavailable(f"snapshot root is not an object: {candidate}")
    schema = payload.get("schema")
    if schema != SNAPSHOT_SCHEMA:
        raise OracleUnavailable(
            f"snapshot schema mismatch: {candidate} (got {schema!r}, want {SNAPSHOT_SCHEMA!r})"
        )
    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, dict):
        raise OracleUnavailable(f"snapshot has no facts object: {candidate}")
    facts = LegacyFacts.from_dict(raw_facts)
    meta = {key: value for key, value in payload.items() if key != "facts"}
    return facts, meta


def snapshot_sha256(path: Path) -> str:
    """Return the sha256 of a snapshot file (for the ledger pin / K-14 措辞).

    Args:
        path: Snapshot path.

    Returns:
        Lowercase hex digest.

    Raises:
        OracleUnavailable: If the file cannot be read.
    """
    try:
        data = Path(path).expanduser().read_bytes()
    except OSError as exc:
        raise OracleUnavailable(f"snapshot unreadable: {path} ({exc})") from exc
    return hashlib.sha256(data).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Write or verify a snapshot from the command line (self-check aid).

    Args:
        argv: Arguments without program name.

    Returns:
        ``0`` success / ``2`` usage / ``21`` oracle unavailable / ``9`` self-test
        failure / ``22`` snapshot write failure.
    """
    parser = argparse.ArgumentParser(
        prog="snapshot.py",
        description="Write/read the O-C oracle snapshot (never inside contracts/).",
    )
    parser.add_argument("--write-snapshot", action="store_true")
    parser.add_argument("--legacy-root", type=Path, default=None)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--contracts", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = _SCRIPTS_DIR.parent
    contracts_dir = args.contracts or repo_root / "contracts"
    snapshot_path = args.snapshot or default_snapshot_path(repo_root)

    if args.self_test:
        return _self_test(repo_root, contracts_dir, snapshot_path)

    if not args.write_snapshot:
        parser.error("nothing to do: pass --write-snapshot or --self-test")
        return 2
    if args.legacy_root is None:
        parser.error("--write-snapshot requires --legacy-root (O-A must succeed first)")
        return 2

    oracle = LegacyOracle(args.legacy_root, timeout_s=args.timeout)
    try:
        facts = oracle.scan()
    except (OracleUnavailable, ReadonlyViolation) as exc:
        print(f"[oracle] UNAVAILABLE {exc} -> snapshot NOT written")
        return 21
    try:
        write_snapshot(facts, snapshot_path, contracts_dir=contracts_dir, oracle_tier="O-A")
    except SnapshotError as exc:
        print(f"[oracle] SNAPSHOT-REFUSED {exc}")
        return 22
    digest = snapshot_sha256(snapshot_path)
    print(f"[oracle] snapshot written: {snapshot_path}")
    print(f"[oracle] snapshot sha256: {digest}")
    print(
        "[oracle] "
        f"{DEGRADED_MARKER}: this file is the weak O-C tier (可改文件, 非外部真值)"
    )
    return 0


def _self_test(repo_root: Path, contracts_dir: Path, snapshot_path: Path) -> int:
    """Run the snapshot module's own checks.

    Covers: (1) ``contracts/`` write refusal, (2) round-trip fidelity,
    (3) missing-file behaviour (unavailable, not empty), (4) empty-payload refusal.

    Returns:
        ``0`` all checks passed, ``9`` otherwise.
    """
    failures: list[str] = []
    checks = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal checks
        checks += 1
        if condition:
            print(f"[oracle] self-test OK   {name}")
            return
        failures.append(f"{name}: {detail}")
        print(f"[oracle] self-test FAIL {name} {detail}")

    # 1) contracts/ 写入必须被拒。
    try:
        assert_writable_target(contracts_dir / "oracle-snapshot.json", contracts_dir)
        check("contracts-write-refused", False, "no SnapshotError raised")
    except SnapshotError as exc:
        check("contracts-write-refused", True, str(exc))

    # 2) 空 facts 必须被拒（空快照 = 假值）。
    empty = LegacyFacts(
        legacy_root="<self-test>",
        scanned_at=_utc_now_iso(),
        openapi_paths=(),
        openapi_operations=(),
        ddl_tables=(),
        ddl_columns=(),
        ddl_indexes=(),
        ddl_raw_indexes=(),
        sse_channels=(),
        error_codes=(),
    )
    try:
        write_snapshot(empty, snapshot_path, contracts_dir=contracts_dir)
        check("empty-snapshot-refused", False, "no SnapshotError raised")
    except SnapshotError as exc:
        check("empty-snapshot-refused", True, str(exc))

    # 3) 缺文件 ⇒ OracleUnavailable（不是"空真值"）。
    try:
        read_snapshot(repo_root / "output" / "e2e" / "__no_such_snapshot__.json")
        check("missing-snapshot-unavailable", False, "no OracleUnavailable raised")
    except OracleUnavailable as exc:
        check("missing-snapshot-unavailable", True, str(exc))

    # 4) round-trip：to_dict -> from_dict 必须逐面相等。
    sample = LegacyFacts(
        legacy_root="<self-test>",
        scanned_at="2026-10-21T00:00:00Z",
        openapi_paths=("/health", "/api/v1/agents"),
        openapi_operations=("GET /api/v1/agents",),
        ddl_tables=("agent", "memory"),
        ddl_columns=(("agent", "id"), ("memory", "vector")),
        ddl_indexes=("ix_agent_created_by",),
        ddl_raw_indexes=(),
        sse_channels=("agent.started",),
        error_codes=("NOT_FOUND",),
        notes=("self-test",),
        chain=("0001", "0002"),
    )
    restored = LegacyFacts.from_dict(json.loads(json.dumps(sample.to_dict())))
    # ``from_dict`` 会对每个面做排序（快照确定性），故按排序后比较。
    check(
        "roundtrip",
        sorted(restored.openapi_paths) == sorted(sample.openapi_paths)
        and sorted(restored.ddl_columns) == sorted(sample.ddl_columns)
        and sorted(restored.ddl_indexes) == sorted(sample.ddl_indexes)
        and sorted(restored.sse_channels) == sorted(sample.sse_channels)
        and sorted(restored.error_codes) == sorted(sample.error_codes)
        and restored.chain == sample.chain,
        f"restored={restored!r}",
    )

    print(f"[oracle] self-test: {checks - len(failures)}/{checks} passed")
    if failures:
        for failure in failures:
            print(f"[oracle] self-test detail {failure}")
        return 9
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(main())
