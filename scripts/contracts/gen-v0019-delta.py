#!/usr/bin/env python3
"""V0.3.0 契约增量 v0019 生成器（**人工登记的 TS 线增量，不是 py 抽取**）。

背景
----
`contracts/` 的 v0018 是从 py 线一次性抽取并冻结的 oracle。`stop_reason`（终态原因，
Harness §1 的 11 值）与 `status` 枚举是 TS 线新增的设计要求，py 线本身没有
（`_old/.../models/conversation.py` 的 `AgentRun` 无该列）。因此本脚本：

* **只读** v0018（不修改、不重钉 v0018 的 sha256）；
* 产出 v0019 全量快照（OpenAPI + 双档 DDL），来源标记 `manual`；
* 生成 `contracts/v0019.manifest.sha256` 作为 v0019 自身的字节级台账。

增量（唯一）
------------
1. `agent_run.stop_reason VARCHAR(50) NULL`（PG / SQLite 同名同型，无方言差异）；
2. `RunResponse.stop_reason` / `RunOut.stop_reason`：`string | null`；
3. `RunResponse.status` / `RunOut.status`：显式 7 值枚举，默认统一 `QUEUED`；
4. `info.version`：`0.4.8` → `0.3.0`（迭代号 = 版本号，V0.3.0 生效）；
5. **不动** SSE 19 帧、不动 `ToolCall` 公开面、不动 paths/operations/schemas 计数。

用法
----
    python scripts/contracts/gen-v0019-delta.py          # 生成/覆盖 v0019
    python scripts/contracts/gen-v0019-delta.py --check  # 校验已生成文件与当前脚本一致

退出码：0 成功/一致；1 `--check` 发现漂移；2 输入缺失。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"

BASE_OPENAPI = CONTRACTS / "openapi.v1.frozen.json"
BASE_PG = CONTRACTS / "schema.v0018.pg.sql"
BASE_SQLITE = CONTRACTS / "schema.v0018.sqlite.sql"

OUT_OPENAPI = CONTRACTS / "openapi.v1.frozen.v0019.json"
OUT_PG = CONTRACTS / "schema.v0019.pg.sql"
OUT_SQLITE = CONTRACTS / "schema.v0019.sqlite.sql"
OUT_MANIFEST = CONTRACTS / "v0019.manifest.sha256"

RUN_STATUSES = [
    "QUEUED",
    "RUNNING",
    "WAITING_APPROVAL",
    "WAITING_INPUT",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
]

STOP_REASONS = [
    "model_finish",
    "tool_failed",
    "approval_rejected",
    "cancelled",
    "budget_tokens",
    "budget_cost",
    "budget_turns",
    "budget_tools",
    "wall_time",
    "provider_error",
    "unknown_recovery",
]

STOP_REASON_SCHEMA = {
    "anyOf": [{"type": "string"}, {"type": "null"}],
    "description": (
        "终态原因（11 值："
        + " / ".join(STOP_REASONS)
        + "）；非终态为 null。与 status 正交：status 是生命周期，stop_reason 是终止原因。"
    ),
    "title": "Stop Reason",
}

STATUS_SCHEMA = {
    "default": "QUEUED",
    "description": "运行生命周期状态；WAITING_APPROVAL / WAITING_INPUT 为可恢复暂停态。",
    "enum": RUN_STATUSES,
    "title": "Status",
    "type": "string",
}


def _fail(message: str) -> None:
    print(f"[v0019] ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_openapi() -> bytes:
    document = json.loads(BASE_OPENAPI.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]

    for name in ("RunResponse", "RunOut"):
        if name not in schemas:
            _fail(f"OpenAPI 缺少 schema {name}")
        properties = schemas[name].setdefault("properties", {})
        properties["status"] = dict(STATUS_SCHEMA)
        properties["stop_reason"] = dict(STOP_REASON_SCHEMA)

    document["info"]["version"] = "0.3.0"
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _insert_column(sql: str, dialect: str) -> str:
    pattern = re.compile(
        r"(CREATE TABLE agent_run \(\n)(.*?)(\n\);)", re.DOTALL
    )
    match = pattern.search(sql)
    if match is None:
        _fail(f"{dialect}: 未找到 CREATE TABLE agent_run 块")

    body = match.group(2)
    if "stop_reason" in body:
        _fail(f"{dialect}: v0018 里已存在 stop_reason，基线可能已被污染")

    anchor = "\terror TEXT, "
    if body.count(anchor) != 1:
        _fail(f"{dialect}: agent_run 的 `error TEXT,` 锚点数量为 {body.count(anchor)}（期望 1）")

    new_body = body.replace(anchor, anchor + "\n\tstop_reason VARCHAR(50), ", 1)
    return sql[: match.start(2)] + new_body + sql[match.end(2) :]


def _count_agent_run_columns(sql: str) -> int:
    match = re.search(r"CREATE TABLE agent_run \(\n(.*?)\n\);", sql, re.DOTALL)
    if match is None:
        _fail("统计列数失败：未找到 agent_run")
    count = 0
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT", "UNIQUE")):
            continue
        count += 1
    return count


def _count_columns(sql: str) -> int:
    total = 0
    for match in re.finditer(r"CREATE TABLE \w+ \(\n(.*?)\n\);", sql, re.DOTALL):
        for line in match.group(1).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(
                ("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT", "UNIQUE")
            ):
                continue
            total += 1
    return total


def build_ddl(path: Path, dialect: str) -> bytes:
    sql = path.read_text(encoding="utf-8")
    before = _count_agent_run_columns(sql)
    after_sql = _insert_column(sql, dialect)
    after = _count_agent_run_columns(after_sql)
    if after != before + 1:
        _fail(f"{dialect}: agent_run 列数 {before} → {after}（期望 +1）")
    return after_sql.encode("utf-8")


def build_all() -> dict[str, bytes]:
    for path in (BASE_OPENAPI, BASE_PG, BASE_SQLITE):
        if not path.is_file():
            _fail(f"缺少输入 {path.relative_to(ROOT)}")
    return {
        OUT_OPENAPI.name: build_openapi(),
        OUT_PG.name: build_ddl(BASE_PG, "pg"),
        OUT_SQLITE.name: build_ddl(BASE_SQLITE, "sqlite"),
    }


def render_manifest(outputs: dict[str, bytes]) -> bytes:
    lines = [f"{_sha256(data)}  {name}" for name, data in sorted(outputs.items())]
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/校验 V0.3.0 契约增量 v0019")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args()

    outputs = build_all()
    manifest = render_manifest(outputs)

    if args.check:
        for name, data in outputs.items():
            target = CONTRACTS / name
            if not target.is_file():
                print(f"[v0019] MISSING {name}", file=sys.stderr)
                return 1
            if target.read_bytes() != data:
                print(f"[v0019] DRIFT {name}", file=sys.stderr)
                return 1
        if not OUT_MANIFEST.is_file() or OUT_MANIFEST.read_bytes() != manifest:
            print("[v0019] DRIFT v0019.manifest.sha256", file=sys.stderr)
            return 1
        print("[v0019] CHECK OK（3 产物 + manifest 与生成器一致）")
        return 0

    for name, data in outputs.items():
        (CONTRACTS / name).write_bytes(data)
    OUT_MANIFEST.write_bytes(manifest)

    document = json.loads(outputs[OUT_OPENAPI.name])
    print("[v0019] 生成完成：")
    print(
        f"  paths={len(document['paths'])} "
        f"operations={sum(1 for ops in document['paths'].values() for m in ops if m in {'get','post','put','patch','delete'})} "
        f"schemas={len(document['components']['schemas'])}"
    )
    pg_columns = _count_columns(outputs[OUT_PG.name].decode())
    sqlite_columns = _count_columns(outputs[OUT_SQLITE.name].decode())
    print(f"  columns(pg)={pg_columns} columns(sqlite)={sqlite_columns}（610? 以实际为准）")
    print(f"  agent_run columns(pg)={_count_agent_run_columns(outputs[OUT_PG.name].decode())}")
    print(f"  manifest={OUT_MANIFEST.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
