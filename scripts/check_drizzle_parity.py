#!/usr/bin/env python3
"""DoD#1 / DoD#2 —— TS 线（Drizzle）双档数据层与冻结契约的 parity 门禁。

它守什么
--------
V0.1.0 用 **Drizzle ORM（TS）** 重建了 61 张表的数据层。旧 Python 线的 DDL 已被冻结成契约
（``contracts/schema.v0018.{pg,sqlite}.normalized.json`` + ``.sql``）。本门禁回答一个问题：

    **新 TS 线（schema 对象 + 由其发出的双档 DDL），与冻结契约是否零差异？**

四条输入（缺任一条 ⇒ 以退出码 2 退出，**不**退化为绿）
----------------------------------------------------
1. ``output/drizzle-introspect.{pg,sqlite}.json`` —— **运行时自省**产物：把真实 drizzle 表对象
   import 进来用 ``getTableConfig()`` 读出列 / 主键 / 唯一约束 / 外键 / 索引（``pnpm --filter
   @wbtime/db run introspect`` 产出）。这是「TS schema 真身」的证据。
2. ``output/ddl.pg.sql`` / ``output/ddl.sqlite.sql`` —— ``scripts/gen-ddl.ts`` 发出的可执行 DDL
   文本（index 对象 / hnsw / SQLite 专用对象只能从这里核）。
3. 冻结 oracle ``contracts/schema.v0018.{pg,sqlite}.normalized.json``。
4. 类型 oracle ``contracts/db/type-map.csv``（断言组 C / DoD#2）。

为什么不再用正则扫 TypeScript
----------------------------
本门禁 2026-10-21 首版用正则解析 ``packages/db/src/schema/{pg,sqlite}/*.ts``，首跑报 32 条差异，
逐条核查后**没有一条是产物缺陷**，全部是解析器自己看错：
``checksum`` / ``checkout_ref`` 因为 ``part.startswith("CHECK")`` 被当成 CHECK 约束丢掉；
``REFERENCES "user"`` 因为正则只认 ``\\w+`` 而整条外键丢失；SQLite 触发器体里的 ``;`` 让
``BEGIN…END`` 被撕碎。**正则解析 TypeScript / SQL 是脆弱设计**，所以断言组 B 改为
「读运行时自省 JSON，结构对结构比较」，DDL 侧解析器也补齐了这三处缺陷并各自配了反例。

硬断言（少一条这条门禁就不成立）
------------------------------
A0 **绝对计数**（字面量，不随契约漂移）：61 表 / 629 列 / metadata 索引 174 /
   unique 7 / partial 1 / unique 约束 29 / 外键 159 / 索引对象 PG 176、SQLite 174 / hnsw 2。
   **契约自身与自省、DDL 三方都必须命中同一组字面量**，任何一方漂移都单独报红。
A1 DDL 归一化后的表数 / 列数 / 索引对象数与契约 ``counts`` 逐项相等。
A2 表名集合、逐表列名（含顺序）、逐列可空性一致；*类型不参与判定*（``UUID`` vs ``CHAR(36)``
   是预期方言差异，只报 INFO）。
A3 **hnsw 恰好 2 个**，名字集合相等。hnsw **不是** drizzle schema 的职责（ORM 编译不出
   ``USING hnsw``），来源登记为 ``migration raw DDL``（见 ``RAW_HNSW_SOURCES``）。
A4 SQLite 方言专属对象 **恰好 8 个**（虚表 1 + 影子表 4 + 触发器 3），来源登记为
   ``migration raw DDL``（见 ``DIALECT_ONLY_SOURCES``）—— 不假装是 drizzle 生成的。
A5 **空/缺集合必红**：归一化后表数/列数/索引数低于契约的一半 ⇒ ``INVALID(EMPTY)``，
   不允许「两边都空所以相等」（K-11 哑真防范）。
B  自省 JSON 与契约**结构对结构**：表集合、列名与顺序、可空性、主键、唯一约束（名+列）、
   外键（名+列+引用表+引用列）、索引（名+表+列+unique+是否 partial）逐项相等；
   并校验 JSON 里的 ``source.files`` sha256 与磁盘上的 ``schema/**/*.ts`` 一致
   （**改了 schema 没重跑自省 ⇒ red: src.stale**）。
C  ``type-map.csv`` 的 629 行逐列有映射；两个敏感口径（emit 差异 401 / 声明敏感族 403）
   **由脚本实跑输出**，与文档登记值比对 —— 数对不上时**两边都保留**。

🚨 PG 权威库状态
---------------
本机 **无 psql**、服务器 SSH 不通，故本门禁是**离线 parity**：「生成文本/自省结构 ↔ 冻结文本」。
它**不**等于「PG 实例里跑通」。SQLite 档的结果**不得**记为 PG 档 PASS（见 ``xview`` 段的声明）。

Exit codes（与 scripts/_gate_io.py 同一张表）
-------------------------------------------
* ``0`` — 三方零差异；
* ``1`` — 发现差异（注入用例要打出的红）；
* ``2`` — 用法错误 / 产物无法加载；
* ``9`` — ``--self-test`` 失败（注入没有变红，或红的原因不对）。

用法::
    python scripts/check_drizzle_parity.py
    python scripts/check_drizzle_parity.py --self-test
    python scripts/check_drizzle_parity.py --regen          # 先跑 node 自省再校验
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

# --- exit codes（与 _gate_io.py 保持一致，本文件自带一份以免跨文件耦合）--------------
EXIT_OK: Final[int] = 0
EXIT_VIOLATION: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_SELFTEST: Final[int] = 9

TAG: Final[str] = "drizzle-parity"

REPO: Final[Path] = Path(__file__).resolve().parents[1]

DEFAULT_PG_DDL: Final[Path] = REPO / "output" / "ddl.pg.sql"
DEFAULT_SQLITE_DDL: Final[Path] = REPO / "output" / "ddl.sqlite.sql"
DEFAULT_INTROSPECT_DIR: Final[Path] = REPO / "output"
PG_CONTRACT: Final[Path] = REPO / "contracts" / "schema.v0018.pg.normalized.json"
SQLITE_CONTRACT: Final[Path] = REPO / "contracts" / "schema.v0018.sqlite.normalized.json"
TYPE_MAP: Final[Path] = REPO / "contracts" / "db" / "type-map.csv"
SCHEMA_ROOT: Final[Path] = REPO / "packages" / "db" / "src" / "schema"
INTROSPECT_ENTRY: Final[Path] = REPO / "packages" / "db" / "dist" / "schema" / "_introspect.js"

#: 文档登记的 type-map 两个敏感口径（仅用于比对，**不参与计算** —— 计算一律走 CSV 实跑）。
DOCUMENTED_SENSITIVE: Final[dict[str, int]] = {"emit_diff": 401, "declared_family": 403}

#: 口径 B 的方言敏感族（与 gen_type_map.py:110 ``_DIALECT_FAMILY`` 逐字一致）。
_DIALECT_FAMILY: Final[tuple[str, ...]] = ("GUID", "DateTime", "JSON", "JSONType", "VectorType")

#: A0 —— 绝对计数。**字面量**，不由契约推导：契约变了就必须有人来解释为什么改这里。
EXPECTED_COUNTS: Final[dict[str, int]] = {
    "tables": 61,
    "columns": 629,
    "metadata_indexes": 174,
    "unique_indexes": 7,
    "partial_indexes": 1,
    "unique_constraints": 29,
    "foreign_keys": 159,
}
EXPECTED_INDEX_OBJECTS: Final[dict[str, int]] = {"pg": 176, "sqlite": 174}
EXPECTED_HNSW: Final[int] = 2

#: A4 —— SQLite 方言专属对象：**来源是 migration raw DDL，不是 drizzle schema**。
#: drizzle 的 sqlite-core 表达不了 ``CREATE VIRTUAL TABLE … USING fts5``、
#: FTS5 的影子表以及 ``CREATE TRIGGER``，所以这 8 个对象的唯一合法出处是迁移原文。
DIALECT_ONLY_REGISTRY: Final[dict[str, int]] = {"virtual_table": 1, "shadow_table": 4, "trigger": 3}
DIALECT_ONLY_SOURCES: Final[dict[str, str]] = {
    "virtual_table": "migration raw DDL · 0013_phase2_knowledge：CREATE VIRTUAL TABLE … USING fts5",
    "shadow_table": "FTS5 内部影子表（sqlite_master 回读；源文件无独立 DDL）",
    "trigger": "migration raw DDL · 0013_phase2_knowledge：document_chunk_ai / _ad / _au",
}

#: A3 —— PG 的 2 个 hnsw 索引同样**不是** drizzle schema 能表达的（ORM 不出 ``USING hnsw``），
#: 唯一合法出处是迁移里的 raw DDL。
RAW_HNSW_SOURCES: Final[dict[str, str]] = {
    "ix_embedding_vector_hnsw": "migration raw DDL · 0013_phase2_knowledge",
    "ix_memory_vector_hnsw": "migration raw DDL · 0014_phase2_memory",
}

#: 低于该比例即判定为「集合可疑地空」—— 防「两边都空⇒相等」的哑真。
EMPTY_RATIO: Final[float] = 0.5


# ---------------------------------------------------------------------------
# Diff 记录
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Diff:
    """一条差异记录：``kind`` 决定调用方能按名检索期望的红。"""

    kind: str
    subject: str
    detail: str

    def render(self) -> str:
        return f"[{self.kind}] {self.subject} :: {self.detail}"


@dataclass
class Report:
    diffs: list[Diff] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def red(self, kind: str, subject: str, detail: str) -> None:
        self.diffs.append(Diff(kind=kind, subject=subject, detail=detail))

    def note(self, line: str) -> None:
        self.info.append(line)

    def has_kind(self, kind: str) -> bool:
        return any(d.kind == kind for d in self.diffs)

    def from_contains(self, kind: str, needle: str) -> bool:
        return any(d.kind == kind and needle in d.subject for d in self.diffs)

    def from_detail_contains(self, kind: str, needle: str) -> bool:
        return any(d.kind == kind and needle in d.detail for d in self.diffs)


def log(msg: str) -> None:
    """单行输出（K-7：一条记录一行，禁止多行折叠）。"""
    sys.stdout.write(f"[{TAG}] {msg}\n")


# ---------------------------------------------------------------------------
# 输入加载
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"缺文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"缺文件：{path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# DDL 归一化：文本 → 结构
# ---------------------------------------------------------------------------


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    default: str | None


@dataclass
class Index:
    name: str
    table: str
    columns: list[str]
    unique: bool
    where: str | None
    method: str | None = None  # 仅 PG raw 索引（hnsw）有值


@dataclass
class UniqueConstraint:
    name: str
    table: str
    columns: list[str]


@dataclass
class ForeignKey:
    name: str | None
    table: str
    columns: list[str]
    referred_table: str
    referred_columns: list[str]


@dataclass
class Table:
    name: str
    columns: list[Column]
    primary_key: list[str]
    uniques: list[UniqueConstraint]
    foreign_keys: list[ForeignKey]


@dataclass
class Normalized:
    dialect: str
    tables: dict[str, Table]
    indexes: dict[str, Index]
    unique_indexes: int = 0
    partial_indexes: int = 0
    raw_indexes: list[Index] = field(default_factory=list)
    raw_sql_re: int = 0
    extensions: list[str] = field(default_factory=list)
    virtual_tables: list[str] = field(default_factory=list)
    shadow_tables: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)


def iter_statements(sql: str) -> Iterable[str]:
    """按 ``;`` 切语句：感知 ``--`` 注释、单引号串、括号深度、``BEGIN…END``（SQLite 触发器）。

    触发器体里含 ``;``（``BEGIN INSERT …; INSERT …; END;``），必须在 ``BEGIN/END``
    配平后才允许切分，否则触发器会被撕成碎片 —— 那是「SQLite 专属 8 个对象」对账失真的经典坑。

    ⚠️ 2026-10-21 修：原实现把「词法 token 的判定」放在 ``;`` 判定**之后**，于是 ``END;``
    里的 ``END`` 还没被识别成 END，``trigger_depth`` 仍是 1，``;`` 不敢切分 —— 结果第 1 个
    触发器之后的三条语句被吞成一条，3 个触发器只解析出 1 个。现在先 flush 词法再判 ``;``。
    """
    buf: list[str] = []
    depth = 0
    in_str = False
    trigger_depth = 0
    is_trigger = False
    word: list[str] = []
    i = 0
    n = len(sql)

    def flush_word() -> None:
        nonlocal is_trigger, trigger_depth, word
        token = "".join(word).upper()
        word = []
        if not token:
            return
        if token == "TRIGGER":
            is_trigger = True
        elif is_trigger and token == "BEGIN":
            trigger_depth += 1
        elif is_trigger and token == "END" and trigger_depth > 0:
            trigger_depth -= 1

    while i < n:
        ch = sql[i]
        if not in_str and ch == "-" and sql[i + 1 : i + 2] == "-":
            flush_word()
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if in_str:
            buf.append(ch)
            if ch == "'":
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            flush_word()
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            flush_word()
            depth -= 1
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            flush_word()
            if depth == 0 and trigger_depth == 0:
                stmt = "".join(buf).strip()
                if stmt:
                    yield stmt
                buf = []
                is_trigger = False
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            word.append(ch)
        else:
            flush_word()
        buf.append(ch)
        i += 1

    flush_word()
    tail = "".join(buf).strip()
    if tail:
        yield tail


def strip_comments(sql: str) -> str:
    out = []
    for line in sql.splitlines():
        # 极简处理：本工程 DDL 里的 '--' 一律是行注释（字符串内的 '--' 不存在）
        idx = line.find("--")
        out.append(line if idx < 0 else line[:idx])
    return "\n".join(out)


def split_top_level(body: str) -> list[str]:
    """按深度 0 的逗号切分 CREATE TABLE 体段。"""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    in_str = False
    for ch in body:
        if in_str:
            cur.append(ch)
            if ch == "'":
                in_str = False
            continue
        if ch == "'":
            in_str = True
            cur.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


#: 标识符：裸名 或 "带引号"（PG 保留字如 ``user`` 会被引号包起来）。
_IDENT: Final[str] = r'("[^"]+"|[A-Za-z_][\w$]*)'
_CHECK_RE: Final[re.Pattern[str]] = re.compile(r"^CHECK\s*\(", re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(
    rf"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}\s*\(", re.IGNORECASE
)
_CREATE_INDEX_RE = re.compile(
    rf"^CREATE\s+(UNIQUE\s+)?INDEX\s+{_IDENT}\s+ON\s+{_IDENT}\s*\((.*?)\)\s*(?:WHERE\s+(.*))?$",
    re.IGNORECASE | re.DOTALL,
)
_CREATE_RAW_INDEX_RE = re.compile(
    r"^CREATE\s+INDEX\s+(\w+)\s+ON\s+(\w+)\s+USING\s+(\w+)\s*\((.*?)\)\s*(?:WITH\s*\((.*?)\))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
#: ⚠️ 2026-10-21 修：表名/引用表名都可能是 "user" 这种带引号标识符，原 ``\w+`` 会整条漏掉。
_ALTER_FK_RE = re.compile(
    rf"^ALTER\s+TABLE\s+{_IDENT}\s+ADD\s+(?:CONSTRAINT\s+{_IDENT}\s+)?FOREIGN\s+KEY\s*"
    rf"\(([^)]*)\)\s*REFERENCES\s+{_IDENT}\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_INLINE_UQ_RE = re.compile(rf"^CONSTRAINT\s+{_IDENT}\s+UNIQUE\s*\(([^)]*)\)", re.IGNORECASE)
_INLINE_FK_RE = re.compile(
    rf"^(?:CONSTRAINT\s+{_IDENT}\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+{_IDENT}\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_PK_RE = re.compile(r"^PRIMARY\s+KEY\s*\(([^)]*)\)", re.IGNORECASE)
_CREATE_VIRTUAL_RE = re.compile(r"^CREATE\s+VIRTUAL\s+TABLE\s+(\w+)", re.IGNORECASE)
_CREATE_TRIGGER_RE = re.compile(r"^CREATE\s+TRIGGER\s+(\w+)", re.IGNORECASE)
_CREATE_EXT_RE = re.compile(r"^CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.IGNORECASE)
_CREATE_SHADOW_RE = re.compile(r"^CREATE\s+TABLE\s+'([^']+)'", re.IGNORECASE)
#: 影子表**只能登记、不能重放**（SQLite 保留名）。DDL 用注释行登记，形如
#: ``-- shadow-table: document_chunk_fts_data | source: …``。
_SHADOW_DECL_RE = re.compile(r"^--\s*shadow-table:\s*([\w$]+)\s*\|", re.MULTILINE)

_NOT_NULL_RE = re.compile(r"\bNOT\s+NULL\b", re.IGNORECASE)
_DEFAULT_RE = re.compile(r"\bDEFAULT\s+(.+?)(?:\s+NOT\s+NULL\s*)?$", re.IGNORECASE)


def parse_shadow_registry(text: str) -> list[str]:
    """从 DDL 注释里读回「影子表登记清单」（它们由 FTS5 自动建，不在可执行语句里）。"""
    return sorted(m.group(1) for m in _SHADOW_DECL_RE.finditer(text))


def unquote(name: str) -> str:
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        return name[1:-1]
    return name


def parse_column(part: str) -> Column:
    tokens = part.split()
    name = unquote(tokens[0])
    rest = part[len(tokens[0]) :].strip()
    nullable = not bool(_NOT_NULL_RE.search(rest))
    default: str | None = None
    m = _DEFAULT_RE.search(rest)
    if m:
        default = m.group(1).strip()
    type_part = rest
    dm = re.search(r"\bDEFAULT\b", rest, re.IGNORECASE)
    if dm:
        type_part = rest[: dm.start()].strip()
    else:
        nn = re.search(r"\bNOT\s+NULL\b", rest, re.IGNORECASE)
        if nn:
            type_part = rest[: nn.start()].strip()
    return Column(name=name, type=type_part.strip(), nullable=nullable, default=default)


def normalize_ddl(text: str, dialect: str) -> Normalized:
    """把生成的 DDL 文本归一化成可与 frozen normalized json 直接比对的结构。"""
    norm = Normalized(dialect=dialect, tables={}, indexes={})
    clean = strip_comments(text)

    for stmt in iter_statements(clean):
        stmt = stmt.strip()
        if not stmt:
            continue

        m = _CREATE_TABLE_RE.match(stmt)
        if m:
            table_name = unquote(m.group(1))
            open_idx = stmt.find("(")
            depth = 0
            end = -1
            for i in range(open_idx, len(stmt)):
                if stmt[i] == "(":
                    depth += 1
                elif stmt[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0:
                raise ValueError(f"CREATE TABLE 括号不配平：{table_name}")
            body = stmt[open_idx + 1 : end]
            table = Table(name=table_name, columns=[], primary_key=[], uniques=[], foreign_keys=[])
            for part in split_top_level(body):
                pk = _PK_RE.match(part)
                if pk:
                    table.primary_key = [unquote(c.strip()) for c in pk.group(1).split(",")]
                    continue
                uq = _INLINE_UQ_RE.match(part)
                if uq:
                    table.uniques.append(
                        UniqueConstraint(
                            name=unquote(uq.group(1)),
                            table=table_name,
                            columns=[unquote(c.strip()) for c in uq.group(2).split(",")],
                        )
                    )
                    continue
                fk = _INLINE_FK_RE.match(part)
                if fk:
                    table.foreign_keys.append(
                        ForeignKey(
                            name=unquote(fk.group(1)) if fk.group(1) else None,
                            table=table_name,
                            columns=[unquote(c.strip()) for c in fk.group(2).split(",")],
                            referred_table=unquote(fk.group(3).strip()),
                            referred_columns=[unquote(c.strip()) for c in fk.group(4).split(",")],
                        )
                    )
                    continue
                # ⚠️ 2026-10-21 修：原来是 ``part.upper().startswith("CHECK")``，
                # 于是 checksum / checkout_ref 这两类**普通列**被当成 CHECK 约束丢掉（3 列）。
                if _CHECK_RE.match(part):
                    continue
                table.columns.append(parse_column(part))
            norm.tables[table_name] = table
            continue

        raw = _CREATE_RAW_INDEX_RE.match(stmt)
        if raw and dialect == "pg":
            idx = Index(
                name=raw.group(1),
                table=raw.group(2),
                columns=[c.strip() for c in raw.group(4).split(",")],
                unique=False,
                where=None,
                method=raw.group(3).lower(),
            )
            norm.raw_indexes.append(idx)
            norm.indexes[raw.group(1)] = idx
            continue

        idx_m = _CREATE_INDEX_RE.match(stmt)
        if idx_m:
            idx = Index(
                name=unquote(idx_m.group(2)),
                table=unquote(idx_m.group(3)),
                columns=[unquote(c.strip()) for c in idx_m.group(4).split(",")],
                unique=bool(idx_m.group(1)),
                where=(idx_m.group(5) or None),
            )
            norm.indexes[idx.name] = idx
            if idx.unique:
                norm.unique_indexes += 1
            if idx.where:
                norm.partial_indexes += 1
            continue

        fk_m = _ALTER_FK_RE.match(stmt)
        if fk_m:
            table_name = unquote(fk_m.group(1))
            table = norm.tables.get(table_name)
            if table is None:
                raise ValueError(f"ALTER TABLE 指向未知表：{table_name}")
            table.foreign_keys.append(
                ForeignKey(
                    name=unquote(fk_m.group(2)) if fk_m.group(2) else None,
                    table=table_name,
                    columns=[unquote(c.strip()) for c in fk_m.group(3).split(",")],
                    referred_table=unquote(fk_m.group(4)),
                    referred_columns=[unquote(c.strip()) for c in fk_m.group(5).split(",")],
                )
            )
            continue

        ext = _CREATE_EXT_RE.match(stmt)
        if ext:
            norm.extensions.append(ext.group(1))
            continue

        vt = _CREATE_VIRTUAL_RE.match(stmt)
        if vt and dialect == "sqlite":
            if "fts5" in stmt.lower():
                norm.virtual_tables.append(vt.group(1))
            continue

        trg = _CREATE_TRIGGER_RE.match(stmt)
        if trg and dialect == "sqlite":
            norm.triggers.append(trg.group(1))
            continue

        # SQLite 影子表由 sqlite_master 回读，形如 CREATE TABLE 'x'(...) 单引号名字
        if dialect == "sqlite" and _CREATE_SHADOW_RE.match(stmt):
            low = stmt.lower()
            for marker in ("_data", "_idx", "_docsize", "_config", "_content"):
                if marker in low:
                    name_match = _CREATE_SHADOW_RE.match(stmt)
                    if name_match:
                        norm.shadow_tables.append(name_match.group(1))
                    break

    return norm


# ---------------------------------------------------------------------------
# 三种视图
# ---------------------------------------------------------------------------


def contract_view(doc: dict[str, Any]) -> dict[str, Any]:
    """把 frozen normalized json 拉平成与门禁同一形状，便于逐项比对。"""
    tables: dict[str, dict[str, Any]] = {}
    indexes: dict[str, dict[str, Any]] = {}
    for t in doc["tables"]:
        tables[t["name"]] = {
            "columns": [(c["name"], bool(c["nullable"]), c["type"]) for c in t["columns"]],
            "has_default": [c["default"] is not None for c in t["columns"]],
            "primary_key": list(t["primary_key"]),
            "uniques": [(u["name"], list(u["columns"])) for u in t["unique_constraints"]],
            "foreign_keys": [
                (f["name"], list(f["columns"]), f["referred_table"], list(f["referred_columns"]))
                for f in t["foreign_keys"]
            ],
        }
        for ix in t["indexes"]:
            indexes[ix["name"]] = {
                "name": ix["name"],
                "table": t["name"],
                "columns": list(ix["columns"]),
                "unique": bool(ix["unique"]),
                "where": ix["where"],
            }
    return {
        "tables": tables,
        "indexes": indexes,
        "counts": doc["counts"],
        "raw_indexes": doc.get("raw_indexes", []),
        "extensions": [e["name"] for e in doc.get("extensions", [])],
        "dialect_only": [(o["kind"], o["name"]) for o in doc.get("dialect_only", []) if "kind" in o],
        "triggers": sorted(o["name"] for o in doc.get("dialect_only", []) if o.get("kind") == "trigger"),
        "virtual_tables": sorted(
            o["name"] for o in doc.get("dialect_only", []) if o.get("kind") == "virtual_table"
        ),
        "shadow_tables": sorted(
            o["name"] for o in doc.get("dialect_only", []) if o.get("kind") == "shadow_table"
        ),
    }


def introspect_view(doc: dict[str, Any]) -> dict[str, Any]:
    """把运行时自省 JSON 拉平成与契约同一形状。"""
    tables: dict[str, dict[str, Any]] = {}
    indexes: dict[str, dict[str, Any]] = {}
    for t in doc["tables"]:
        tables[t["name"]] = {
            "columns": [(c["name"], bool(c["nullable"]), c["type"]) for c in t["columns"]],
            "has_default": [bool(c["hasDefault"]) for c in t["columns"]],
            "primary_key": list(t["primary_key"]),
            "uniques": [(u["name"], list(u["columns"])) for u in t["unique_constraints"]],
            "foreign_keys": [
                (f["name"], list(f["columns"]), f["referred_table"], list(f["referred_columns"]))
                for f in t["foreign_keys"]
            ],
        }
        for ix in t["indexes"]:
            indexes[ix["name"]] = {
                "name": ix["name"],
                "table": t["name"],
                "columns": list(ix["columns"]),
                "unique": bool(ix["unique"]),
                "where_present": bool(ix["where_present"]),
            }
    return {"tables": tables, "indexes": indexes, "counts": doc["counts"], "source": doc.get("source", {})}


def _empty_guard(rep: Report, dialect: str, measured: int, contract_value: int, what: str) -> None:
    """A5：空/缺集合必红 —— 远低于契约值 ⇒ INVALID(EMPTY)，不管两边是否「相等」。"""
    if contract_value > 0 and measured < contract_value * EMPTY_RATIO:
        rep.red(
            f"{dialect}.EMPTY",
            f"{dialect}.{what}",
            f"INVALID(EMPTY) 归一化后 {what} 只有 {measured} 个，契约要求 {contract_value} 个"
            f"（<{EMPTY_RATIO:.0%}）⇒ 判定为集合缺失而非差异",
        )


def _norm_entry(entry: tuple) -> tuple:
    """两侧统一表示：``None`` → ``""``，列集合 → ``tuple[str]``。

    两个独立原因（2026-10-21 踩过）：
    1. ``referred_table`` 为 ``None`` 时裸 ``sorted()`` 会抛
       ``TypeError: '<' not supported between 'str' and 'NoneType'``；
    2. 契约侧列集合是 JSON ``list``、生成侧是 ``tuple``，``('a', ['b']) != ('a', ('b',))``
       曾报出 181 条纯表示噪声。
    """
    out: list[Any] = []
    for value in entry:
        if value is None:
            out.append("")
        elif isinstance(value, (list, tuple)):
            out.append(tuple(str(item) for item in value))
        else:
            out.append(str(value))
    return tuple(out)


# ---------------------------------------------------------------------------
# 断言组 A1/A2：DDL 侧
# ---------------------------------------------------------------------------


def compare_ddl(
    rep: Report,
    dialect: str,
    norm: Normalized,
    view: dict[str, Any],
    shadow_registry: Sequence[str] = (),
) -> dict[str, Any]:
    counts = view["counts"]
    gen_tables = sorted(norm.tables)
    con_tables = sorted(view["tables"])
    _empty_guard(rep, dialect, len(gen_tables), counts["tables"], "tables")

    for name in sorted(set(gen_tables) - set(con_tables)):
        rep.red(f"{dialect}.table", name, "生成 DDL 有、冻结契约无")
    for name in sorted(set(con_tables) - set(gen_tables)):
        rep.red(f"{dialect}.table", name, "冻结契约有、生成 DDL 无")

    gen_cols = sum(len(t.columns) for t in norm.tables.values())
    _empty_guard(rep, dialect, gen_cols, counts["columns"], "columns")
    if gen_cols != counts["columns"]:
        rep.red(
            f"{dialect}.column-count",
            f"{dialect}.columns",
            f"生成 {gen_cols} 列 / 契约 {counts['columns']} 列",
        )

    gen_meta = len([i for i in norm.indexes.values() if not i.method])
    _empty_guard(rep, dialect, gen_meta, counts["metadata_indexes"], "indexes")
    if gen_meta != counts["metadata_indexes"]:
        rep.red(
            f"{dialect}.index-count",
            f"{dialect}.indexes",
            f"生成 {gen_meta} 个 metadata 索引 / 契约 {counts['metadata_indexes']} 个",
        )
    gen_total = gen_meta + len(norm.raw_indexes)
    if gen_total != counts["index_objects_total"]:
        rep.red(
            f"{dialect}.index-objects-total",
            f"{dialect}.index_objects_total",
            f"生成 {gen_total} / 契约 {counts['index_objects_total']}",
        )
    if norm.unique_indexes != counts["unique_indexes"]:
        rep.red(
            f"{dialect}.unique-index-count",
            f"{dialect}.unique_indexes",
            f"生成 {norm.unique_indexes} / 契约 {counts['unique_indexes']}",
        )
    if norm.partial_indexes != counts["partial_indexes"]:
        rep.red(
            f"{dialect}.partial-index-count",
            f"{dialect}.partial_indexes",
            f"生成 {norm.partial_indexes} / 契约 {counts['partial_indexes']}",
        )

    type_same = 0
    type_total = 0
    for name in sorted(set(gen_tables) & set(con_tables)):
        g = norm.tables[name]
        c = view["tables"][name]
        g_cols = [col.name for col in g.columns]
        c_cols = [x[0] for x in c["columns"]]
        if g_cols != c_cols:
            missing = sorted(set(c_cols) - set(g_cols))
            extra = sorted(set(g_cols) - set(c_cols))
            rep.red(
                f"{dialect}.column",
                name,
                f"列名集合/顺序不一致 缺={missing} 多={extra}" if missing or extra else "列顺序不一致",
            )
        else:
            for i, col in enumerate(g.columns):
                if bool(col.nullable) != bool(c["columns"][i][1]):
                    rep.red(
                        f"{dialect}.column-nullability",
                        f"{name}.{col.name}",
                        f"生成 nullable={col.nullable} / 契约 nullable={c['columns'][i][1]}",
                    )
                type_total += 1
                if col.type.strip().upper() == str(c["columns"][i][2]).strip().upper():
                    type_same += 1

        if list(g.primary_key) != list(c["primary_key"]):
            rep.red(f"{dialect}.primary-key", name, f"生成 {g.primary_key} / 契约 {c['primary_key']}")

        g_uq = sorted(_norm_entry((u.name, tuple(u.columns))) for u in g.uniques)
        c_uq = sorted(_norm_entry(tuple(x)) for x in c["uniques"])
        if g_uq != c_uq:
            rep.red(f"{dialect}.unique-constraint", name, f"生成 {g_uq} / 契约 {c_uq}")

        g_fk = sorted(
            _norm_entry((f.name, tuple(f.columns), f.referred_table, tuple(f.referred_columns)))
            for f in g.foreign_keys
        )
        c_fk = sorted(_norm_entry(tuple(x)) for x in c["foreign_keys"])
        if g_fk != c_fk:
            rep.red(
                f"{dialect}.foreign-key",
                name,
                f"生成 {len(g_fk)} 个 / 契约 {len(c_fk)} 个；差集 生成多={sorted(set(g_fk) - set(c_fk))}"
                f" 契约多={sorted(set(c_fk) - set(g_fk))}",
            )

    gen_idx = {k: v for k, v in norm.indexes.items() if not v.method}
    con_idx = view["indexes"]
    for name in sorted(set(gen_idx) - set(con_idx)):
        rep.red(f"{dialect}.index", name, "生成 DDL 有、冻结契约无")
    for name in sorted(set(con_idx) - set(gen_idx)):
        rep.red(f"{dialect}.index", name, "冻结契约有、生成 DDL 无")
    for name in sorted(set(gen_idx) & set(con_idx)):
        g, insp = gen_idx[name], con_idx[name]
        if g.table != insp["table"]:
            rep.red(f"{dialect}.index-table", name, f"生成挂 {g.table} / 契约挂 {insp['table']}")
        if list(g.columns) != list(insp["columns"]):
            rep.red(f"{dialect}.index-columns", name, f"生成 {g.columns} / 契约 {insp['columns']}")
        if g.unique != insp["unique"]:
            rep.red(f"{dialect}.index-unique", name, f"生成 {g.unique} / 契约 {insp['unique']}")
        if (g.where or None) != (insp["where"] or None):
            rep.red(f"{dialect}.index-where", name, f"生成 {g.where!r} / 契约 {insp['where']!r}")

    if dialect == "pg":
        if sorted(norm.extensions) != sorted(view["extensions"]):
            rep.red(
                f"{dialect}.extension",
                "extensions",
                f"生成 {sorted(norm.extensions)} / 契约 {sorted(view['extensions'])}",
            )
    else:
        if norm.shadow_tables:
            rep.red(
                "sqlite.shadow-executable",
                "dialect_only",
                f"{sorted(norm.shadow_tables)} 被当成可执行 CREATE TABLE 发出 —— "
                "影子表是 FTS5 自动创建的保留名，手工建会 SQLITE_ERROR（object name reserved for internal use）",
            )
        gen_special = (
            [("virtual_table", n) for n in norm.virtual_tables]
            + [("shadow_table", n) for n in shadow_registry]
            + [("trigger", n) for n in norm.triggers]
        )
        if sorted(gen_special) != sorted(view["dialect_only"]):
            rep.red(
                f"{dialect}.dialect-only",
                "dialect_only",
                f"生成 {len(gen_special)} 个 {sorted(gen_special)}"
                f" / 契约 {len(view['dialect_only'])} 个 {sorted(view['dialect_only'])}",
            )

    return {"type_same": type_same, "type_total": type_total}


# ---------------------------------------------------------------------------
# 断言组 B：运行时自省 JSON（结构对结构，零正则）
# ---------------------------------------------------------------------------


def check_source_digests(rep: Report, doc: dict[str, Any]) -> int:
    """自省 JSON 的 ``source.files`` 必须与磁盘上的 schema/**/*.ts 一致（防陈旧哑真）。"""
    source = doc.get("source") or {}
    files = source.get("files") or []
    if not files:
        rep.red("src.missing", "source.files", "自省 JSON 没有 source.files 溯源清单 ⇒ 无法判断是否陈旧")
        return 0

    on_disk = sorted(SCHEMA_ROOT.rglob("*.ts"))
    listed = {entry["path"] for entry in files}
    disk_rel = {
        str(p.relative_to(REPO)).replace("\\", "/")
        for p in on_disk
    }
    for missing in sorted(disk_rel - listed):
        rep.red("src.stale", missing, "磁盘上有该 .ts，自省 JSON 的溯源清单里没有 ⇒ 自省未覆盖")
    for gone in sorted(listed - disk_rel):
        rep.red("src.stale", gone, "自省 JSON 记了该 .ts，磁盘上已不存在 ⇒ 自省陈旧")

    checked = 0
    for entry in files:
        path = REPO / entry["path"]
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checked += 1
        if digest != entry.get("sha256"):
            rep.red(
                "src.stale",
                entry["path"],
                f"sha256 不符：磁盘 {digest[:16]}… / JSON 登记 {str(entry.get('sha256'))[:16]}… ⇒ "
                "schema 改过但没重跑自省（pnpm --filter @wbtime/db run introspect）",
            )
    return checked


def compare_introspect(rep: Report, dialect: str, intro: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """自省结构 ↔ 契约结构，逐项比较。kind 前缀 ``src.`` 以便与 DDL 侧区分。"""
    counts = view["counts"]
    g_tables = intro["tables"]
    c_tables = view["tables"]

    _empty_guard(rep, "src." + dialect, len(g_tables), counts["tables"], "tables")
    for name in sorted(set(c_tables) - set(g_tables)):
        rep.red(f"src.{dialect}.table", name, "冻结契约有该表、drizzle 表对象里没有")
    for name in sorted(set(g_tables) - set(c_tables)):
        rep.red(f"src.{dialect}.table", name, "drizzle 表对象里有该表、冻结契约无")

    g_cols = sum(len(t["columns"]) for t in g_tables.values())
    _empty_guard(rep, "src." + dialect, g_cols, counts["columns"], "columns")
    if g_cols != counts["columns"]:
        rep.red(f"src.{dialect}.column-count", "columns", f"自省 {g_cols} 列 / 契约 {counts['columns']} 列")

    gen_meta = len(intro["indexes"])
    if gen_meta != counts["metadata_indexes"]:
        rep.red(
            f"src.{dialect}.index-count",
            "indexes",
            f"自省 {gen_meta} 个 metadata 索引 / 契约 {counts['metadata_indexes']} 个",
        )

    default_mismatch = 0
    for name in sorted(set(g_tables) & set(c_tables)):
        g = g_tables[name]
        c = c_tables[name]
        g_cols_list = [x[0] for x in g["columns"]]
        c_cols_list = [x[0] for x in c["columns"]]
        if g_cols_list != c_cols_list:
            rep.red(
                f"src.{dialect}.column",
                name,
                f"列名集合/顺序不一致 缺={sorted(set(c_cols_list) - set(g_cols_list))}"
                f" 多={sorted(set(g_cols_list) - set(c_cols_list))}"
                if set(g_cols_list) != set(c_cols_list)
                else "列顺序不一致",
            )
            continue
        for i, col in enumerate(g["columns"]):
            if bool(col[1]) != bool(c["columns"][i][1]):
                rep.red(
                    f"src.{dialect}.column-nullability",
                    f"{name}.{col[0]}",
                    f"自省 nullable={col[1]} / 契约 nullable={c['columns'][i][1]}",
                )
        if list(g["primary_key"]) != list(c["primary_key"]):
            rep.red(
                f"src.{dialect}.primary-key",
                name,
                f"自省 {g['primary_key']} / 契约 {c['primary_key']}",
            )

        g_uq = sorted(_norm_entry((u[0], tuple(u[1]))) for u in g["uniques"])
        c_uq = sorted(_norm_entry(tuple(x)) for x in c["uniques"])
        if g_uq != c_uq:
            rep.red(f"src.{dialect}.unique-constraint", name, f"自省 {g_uq} / 契约 {c_uq}")

        g_fk = sorted(_norm_entry((f[0], tuple(f[1]), f[2], tuple(f[3]))) for f in g["foreign_keys"])
        c_fk = sorted(_norm_entry(tuple(x)) for x in c["foreign_keys"])
        if g_fk != c_fk:
            rep.red(
                f"src.{dialect}.foreign-key",
                name,
                f"自省 {len(g_fk)} 个 / 契约 {len(c_fk)} 个；"
                f"差集 自省多={sorted(set(g_fk) - set(c_fk))} 契约多={sorted(set(c_fk) - set(g_fk))}",
            )

        default_mismatch += sum(
            1
            for i in range(len(g["columns"]))
            if bool(g["has_default"][i]) != bool(c["has_default"][i])
        )

    # 索引：名 / 表 / 列 / unique / 是否 partial（partial 的 SQL 文本由 DDL 侧逐字比对）
    g_idx = intro["indexes"]
    c_idx = view["indexes"]
    for name in sorted(set(c_idx) - set(g_idx)):
        rep.red(f"src.{dialect}.index", name, "冻结契约有该索引、drizzle 表对象里没有")
    for name in sorted(set(g_idx) - set(c_idx)):
        rep.red(f"src.{dialect}.index", name, "drizzle 表对象里有该索引、冻结契约无")
    for name in sorted(set(g_idx) & set(c_idx)):
        g, c = g_idx[name], c_idx[name]
        if g["table"] != c["table"]:
            rep.red(f"src.{dialect}.index-table", name, f"自省挂 {g['table']} / 契约挂 {c['table']}")
        if list(g["columns"]) != list(c["columns"]):
            rep.red(f"src.{dialect}.index-columns", name, f"自省 {g['columns']} / 契约 {c['columns']}")
        if bool(g["unique"]) != bool(c["unique"]):
            rep.red(f"src.{dialect}.index-unique", name, f"自省 {g['unique']} / 契约 {c['unique']}")
        if bool(g["where_present"]) != bool(c["where"]):
            rep.red(
                f"src.{dialect}.index-partial",
                name,
                f"自省 wherePresent={g['where_present']} / 契约 where={c['where']!r}",
            )

    if default_mismatch:
        rep.note(
            f"INFO  {dialect}: {default_mismatch} 列的「有无默认值」在自省与契约间不一致"
            "（drizzle 侧 defaultNow() 等映射差异；本门禁不判定默认值，仅供参考）"
        )

    return {"tables": len(g_tables), "columns": g_cols, "indexes": len(g_idx), "default_mismatch": default_mismatch}


# ---------------------------------------------------------------------------
# 断言组 A3：hnsw（drizzle 表达不了，来源=raw DDL）
# ---------------------------------------------------------------------------


def assert_hnsw(rep: Report, norm: Normalized, view: dict[str, Any], pg_intro: dict[str, Any]) -> None:
    expected = [r for r in view["raw_indexes"] if r.get("method") == "hnsw"]
    expected_names = sorted(r["name"] for r in expected)
    got_names = sorted(i.name for i in norm.raw_indexes if i.method == "hnsw")

    if len(expected) != EXPECTED_HNSW:
        rep.red(
            "pg.HNSW-ORACLE",
            "pg.normalized.raw_indexes",
            f"冻结契约里 method=hnsw 的不是 {EXPECTED_HNSW} 个，而是 {len(expected)} 个 ⇒ oracle 本身已失真",
        )
    if len(got_names) != EXPECTED_HNSW:
        rep.red(
            "pg.hnsw-count",
            "pg.normalized.hnsw_indexes",
            f"生成 {len(got_names)} 个 hnsw {got_names}，硬断言要求恰好 {EXPECTED_HNSW} 个",
        )
    for name in sorted(set(expected_names) - set(got_names)):
        rep.red("pg.hnsw-name", name, "冻结契约有该 hnsw 索引、生成 DDL 无")

    # 来源登记：hnsw 只能来自 migration raw DDL，**不应**出现在 drizzle 自省里。
    for name in expected_names:
        if name not in RAW_HNSW_SOURCES:
            rep.red("pg.hnsw-source", name, "该 hnsw 索引没有登记来源（raw DDL 出处）")
    leaked = sorted(set(expected_names) & set(pg_intro["indexes"]))
    if leaked:
        rep.red(
            "pg.hnsw-source",
            "drizzle-introspect.pg.json",
            f"{leaked} 声称由 drizzle schema 生成 —— hnsw 不是 ORM 能表达的对象，来源登记矛盾",
        )


def assert_dialect_only(rep: Report, view: dict[str, Any], sqlite_intro: dict[str, Any]) -> None:
    """A4：SQLite 专属 8 个对象 —— 来源登记为 migration raw DDL，不假装是 drizzle 生成的。"""
    by_kind: dict[str, int] = {}
    for kind, _name in view["dialect_only"]:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    total = len(view["dialect_only"])
    if total != sum(DIALECT_ONLY_REGISTRY.values()):
        rep.red(
            "sqlite.dialect-only-count",
            "dialect_only",
            f"契约里方言专属对象 {total} 个，硬断言要求 {sum(DIALECT_ONLY_REGISTRY.values())} 个",
        )
    if by_kind != DIALECT_ONLY_REGISTRY:
        rep.red(
            "sqlite.dialect-only-kind",
            "dialect_only",
            f"分类计数 {by_kind} / 登记 {DIALECT_ONLY_REGISTRY}（虚表 1 + 影子表 4 + 触发器 3）",
        )
    for kind in sorted(set(by_kind) - set(DIALECT_ONLY_SOURCES)):
        rep.red("sqlite.dialect-only-source", kind, "该类别没有登记来源（raw DDL 出处）")

    # 这 8 个对象不得出现在 drizzle 自省里：它们不是 schema 的职责。
    names = {name for _kind, name in view["dialect_only"]}
    leaked = sorted(names & set(sqlite_intro["tables"]))
    if leaked:
        rep.red(
            "sqlite.dialect-only-source",
            "drizzle-introspect.sqlite.json",
            f"{leaked} 出现在 drizzle 表对象里 —— 虚表/影子表/触发器不是 drizzle 能表达的对象",
        )


# ---------------------------------------------------------------------------
# 断言组 A0：绝对计数 + 三方一致
# ---------------------------------------------------------------------------


def assert_hard_numbers(rep: Report, stats: dict[str, Any]) -> None:
    for dialect in ("pg", "sqlite"):
        s = stats[dialect]
        ddl = s["ddl"]
        intro = s["introspect"]
        contract = s["contract"]
        pairs = [
            ("tables", ddl["tables"], intro["tables"], contract["tables"]),
            ("columns", ddl["columns"], intro["columns"], contract["columns"]),
            ("metadata_indexes", ddl["metadata_indexes"], intro["metadata_indexes"], contract["metadata_indexes"]),
            ("unique_indexes", ddl["unique_indexes"], intro["unique_indexes"], contract["unique_indexes"]),
            ("partial_indexes", ddl["partial_indexes"], intro["partial_indexes"], contract["partial_indexes"]),
            ("unique_constraints", ddl["unique_constraints"], intro["unique_constraints"], contract["unique_constraints"]),
            ("foreign_keys", ddl["foreign_keys"], intro["foreign_keys"], contract["foreign_keys"]),
        ]
        for what, ddl_v, intro_v, con_v in pairs:
            expected = EXPECTED_COUNTS[what]
            for source, value in (("ddl", ddl_v), ("introspect", intro_v), ("contract", con_v)):
                if value != expected:
                    rep.red(
                        f"hard.{dialect}.{what}",
                        f"{dialect}.{what}",
                        f"{source} 实测 {value}，硬断言要求 {expected}"
                        f"（ddl={ddl_v} introspect={intro_v} contract={con_v}）",
                    )
        expected_objects = EXPECTED_INDEX_OBJECTS[dialect]
        for source, value in (
            ("ddl", ddl["index_objects_total"]),
            ("contract", contract["index_objects_total"]),
        ):
            if value != expected_objects:
                rep.red(
                    f"hard.{dialect}.index_objects_total",
                    f"{dialect}.index_objects_total",
                    f"{source} 实测 {value}，硬断言要求 {expected_objects}",
                )

    if stats["pg"]["ddl"]["hnsw_indexes"] != EXPECTED_HNSW:
        rep.red(
            "hard.pg.hnsw",
            "pg.hnsw_indexes",
            f"实测 {stats['pg']['ddl']['hnsw_indexes']} 个 hnsw，硬断言要求 {EXPECTED_HNSW}",
        )

    sqlite_only = stats["sqlite"]["ddl"]["dialect_only_total"]
    if sqlite_only != sum(DIALECT_ONLY_REGISTRY.values()):
        rep.red(
            "hard.sqlite.dialect_only",
            "sqlite.dialect_only",
            f"实测 {sqlite_only} 个方言专属对象，硬断言要求 {sum(DIALECT_ONLY_REGISTRY.values())}",
        )


def assert_cross_view(rep: Report, stats: dict[str, Any]) -> None:
    """DDL ↔ 自省 两个独立视图必须互相吻合（否则「一份产物、两套说法」）。"""
    for dialect in ("pg", "sqlite"):
        ddl = stats[dialect]["ddl"]
        intro = stats[dialect]["introspect"]
        if ddl["tables"] != intro["tables"]:
            rep.red(
                f"xview.{dialect}.tables",
                "ddl vs introspect",
                f"DDL 解析出 {ddl['tables']} 表 / 自省 {intro['tables']} 表",
            )
        if ddl["columns"] != intro["columns"]:
            rep.red(
                f"xview.{dialect}.columns",
                "ddl vs introspect",
                f"DDL 解析出 {ddl['columns']} 列 / 自省 {intro['columns']} 列",
            )
        if ddl["metadata_indexes"] != intro["metadata_indexes"]:
            rep.red(
                f"xview.{dialect}.indexes",
                "ddl vs introspect",
                f"DDL 解析出 {ddl['metadata_indexes']} 索引 / 自省 {intro['metadata_indexes']} 索引",
            )
        if dialect == "sqlite" and ddl["hnsw_indexes"] != 0:
            rep.red(
                "xview.sqlite.hnsw",
                "sqlite.ddl",
                f"SQLite 档出现 {ddl['hnsw_indexes']} 个 hnsw —— hnsw 是 PG 专属（pgvector），SQLite 侧应合法缺失",
            )


# ---------------------------------------------------------------------------
# 断言组 C：type-map.csv（DoD#2）
# ---------------------------------------------------------------------------


def check_type_map(rep: Report, view: dict[str, Any]) -> dict[str, int]:
    rows = list(csv.DictReader(TYPE_MAP.read_text(encoding="utf-8-sig").splitlines()))
    by_pair = {(r["table"], r["column"]): r for r in rows}

    missing = []
    for tname, tinfo in view["tables"].items():
        for cname, _nullable, _type in tinfo["columns"]:
            if (tname, cname) not in by_pair:
                missing.append(f"{tname}.{cname}")

    if missing:
        rep.red(
            "typemap.missing",
            "type-map.csv",
            f"{len(missing)} 个 (表,列) 缺映射行：{missing[:5]}{'…' if len(missing) > 5 else ''}",
        )

    blank = [k for k, r in by_pair.items() if not r["pg_emit_type"] or not r["sqlite_emit_type"]]
    unmapped = [k for k, r in by_pair.items() if r["strategy"] == "unmapped"]
    if blank:
        rep.red("typemap.blank", "type-map.csv", f"{len(blank)} 行 emit 类型为空：{blank[:5]}")
    if unmapped:
        rep.red("typemap.unmapped", "type-map.csv", f"{len(unmapped)} 行 strategy=unmapped：{unmapped[:5]}")

    emit_diff = [r for r in rows if r["dialect_sensitive"].strip().lower() == "true"]
    family = [r for r in rows if r["declared_type"].split("(")[0] in _DIALECT_FAMILY]
    counts = {"rows": len(rows), "emit_diff": len(emit_diff), "declared_family": len(family)}
    for key in ("emit_diff", "declared_family"):
        if counts[key] != DOCUMENTED_SENSITIVE[key]:
            rep.red(
                f"typemap.{key}",
                "type-map.csv",
                f"实跑 {counts[key]} / 文档登记 {DOCUMENTED_SENSITIVE[key]} —— 两个数都保留，既不改 CSV 也不改文档",
            )
    return counts


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def collect(
    pg_ddl: Path,
    sqlite_ddl: Path,
    pg_intro_path: Path,
    sqlite_intro_path: Path,
    pg_doc: dict[str, Any],
    sqlite_doc: dict[str, Any],
) -> tuple[Report, dict[str, Any]]:
    rep = Report()
    pg_norm = normalize_ddl(load_text(pg_ddl), "pg")
    sqlite_text = load_text(sqlite_ddl)
    sqlite_norm = normalize_ddl(sqlite_text, "sqlite")
    shadow_registry = parse_shadow_registry(sqlite_text)
    pg_view = contract_view(pg_doc)
    sqlite_view = contract_view(sqlite_doc)

    pg_intro_doc = load_json(pg_intro_path)
    sqlite_intro_doc = load_json(sqlite_intro_path)
    pg_intro = introspect_view(pg_intro_doc)
    sqlite_intro = introspect_view(sqlite_intro_doc)

    pg_ddl_stats = compare_ddl(rep, "pg", pg_norm, pg_view)
    sqlite_ddl_stats = compare_ddl(rep, "sqlite", sqlite_norm, sqlite_view, shadow_registry)

    pg_src_stats = compare_introspect(rep, "pg", pg_intro, pg_view)
    sqlite_src_stats = compare_introspect(rep, "sqlite", sqlite_intro, sqlite_view)

    checked_files = check_source_digests(rep, pg_intro_doc)
    check_source_digests(rep, sqlite_intro_doc)

    assert_hnsw(rep, pg_norm, pg_view, pg_intro)
    assert_dialect_only(rep, sqlite_view, sqlite_intro)

    tm = check_type_map(rep, pg_view)

    stats = {
        "pg": {
            "ddl": {
                "tables": len(pg_norm.tables),
                "columns": sum(len(t.columns) for t in pg_norm.tables.values()),
                "metadata_indexes": len([i for i in pg_norm.indexes.values() if not i.method]),
                "unique_indexes": pg_norm.unique_indexes,
                "partial_indexes": pg_norm.partial_indexes,
                "raw_indexes": len(pg_norm.raw_indexes),
                "hnsw_indexes": len([i for i in pg_norm.raw_indexes if i.method == "hnsw"]),
                "index_objects_total": len(pg_norm.indexes),
                "foreign_keys": sum(len(t.foreign_keys) for t in pg_norm.tables.values()),
                "unique_constraints": sum(len(t.uniques) for t in pg_norm.tables.values()),
                "dialect_only_total": 0,
                "type_same": pg_ddl_stats["type_same"],
                "type_total": pg_ddl_stats["type_total"],
            },
            "introspect": {
                "tables": pg_src_stats["tables"],
                "columns": pg_src_stats["columns"],
                "metadata_indexes": pg_src_stats["indexes"],
                "unique_indexes": pg_intro["counts"]["unique_indexes"],
                "partial_indexes": pg_intro["counts"]["partial_indexes"],
                "unique_constraints": pg_intro["counts"]["unique_constraints"],
                "foreign_keys": pg_intro["counts"]["foreign_keys"],
                "default_mismatch": pg_src_stats["default_mismatch"],
            },
            "contract": pg_view["counts"],
            "source_files_checked": checked_files,
        },
        "sqlite": {
            "ddl": {
                "tables": len(sqlite_norm.tables),
                "columns": sum(len(t.columns) for t in sqlite_norm.tables.values()),
                "metadata_indexes": len([i for i in sqlite_norm.indexes.values() if not i.method]),
                "unique_indexes": sqlite_norm.unique_indexes,
                "partial_indexes": sqlite_norm.partial_indexes,
                "raw_indexes": len(sqlite_norm.raw_indexes),
                "hnsw_indexes": len([i for i in sqlite_norm.raw_indexes if i.method == "hnsw"]),
                "index_objects_total": len(sqlite_norm.indexes),
                "foreign_keys": sum(len(t.foreign_keys) for t in sqlite_norm.tables.values()),
                "unique_constraints": sum(len(t.uniques) for t in sqlite_norm.tables.values()),
                "virtual_tables": len(sqlite_norm.virtual_tables),
                "shadow_tables": len(shadow_registry),
                "triggers": len(sqlite_norm.triggers),
                "dialect_only_total": len(sqlite_norm.virtual_tables)
                + len(shadow_registry)
                + len(sqlite_norm.triggers),
                "type_same": sqlite_ddl_stats["type_same"],
                "type_total": sqlite_ddl_stats["type_total"],
            },
            "introspect": {
                "tables": sqlite_src_stats["tables"],
                "columns": sqlite_src_stats["columns"],
                "metadata_indexes": sqlite_src_stats["indexes"],
                "unique_indexes": sqlite_intro["counts"]["unique_indexes"],
                "partial_indexes": sqlite_intro["counts"]["partial_indexes"],
                "unique_constraints": sqlite_intro["counts"]["unique_constraints"],
                "foreign_keys": sqlite_intro["counts"]["foreign_keys"],
                "default_mismatch": sqlite_src_stats["default_mismatch"],
            },
            "contract": sqlite_view["counts"],
            "source_files_checked": checked_files,
        },
        "type_map": tm,
    }

    assert_hard_numbers(rep, stats)
    assert_cross_view(rep, stats)
    return rep, stats


def print_report(stats: dict[str, Any]) -> None:
    log("-" * 74)
    log("实测计数（三方：DDL 解析 / 运行时自省 / 冻结契约；全部实跑，禁手填）")
    for dialect in ("pg", "sqlite"):
        s = stats[dialect]
        ddl = s["ddl"]
        intro = s["introspect"]
        con = s["contract"]
        log(
            f"  {dialect:6s} 表  : ddl {ddl['tables']:>3} / 自省 {intro['tables']:>3} / 契约 {con['tables']:>3}"
            f"   列 : ddl {ddl['columns']:>3} / 自省 {intro['columns']:>3} / 契约 {con['columns']:>3}"
        )
        log(
            f"         idx : ddl {ddl['metadata_indexes']:>3} / 自省 {intro['metadata_indexes']:>3}"
            f" / 契约 {con['metadata_indexes']:>3}"
            f"   索引对象合计 ddl {ddl['index_objects_total']} / 契约 {con['index_objects_total']}"
        )
        log(
            f"         unique {ddl['unique_indexes']} / partial {ddl['partial_indexes']}"
            f" / 外键 ddl {ddl['foreign_keys']} 自省 {intro['foreign_keys']} 契约 {con['foreign_keys']}"
            f" / unique 约束 {ddl['unique_constraints']}"
        )
        log(
            f"         类型逐字一致 {ddl['type_same']}/{ddl['type_total']}（INFO，不参与判定）"
            f" / 默认值差异 {intro['default_mismatch']} 列（INFO）"
        )
    s = stats["sqlite"]["ddl"]
    log(
        f"  sqlite 专属：虚表 {s['virtual_tables']} / 影子表 {s['shadow_tables']} / 触发器 {s['triggers']}"
        f"（合计 {s['dialect_only_total']}，来源= migration raw DDL）"
    )
    log(
        f"  hnsw：{stats['pg']['ddl']['hnsw_indexes']} 个（来源= migration raw DDL，"
        "drizzle schema 不表达 USING hnsw）"
    )
    log(f"  自省溯源：{stats['pg']['source_files_checked']} 个 .ts 的 sha256 与 JSON 一致")
    tm = stats["type_map"]
    log(
        f"  type-map.csv：{tm['rows']} 行；口径A emit 差异 {tm['emit_diff']}"
        f"（文档 {DOCUMENTED_SENSITIVE['emit_diff']}）/ 口径B 声明敏感族 {tm['declared_family']}"
        f"（文档 {DOCUMENTED_SENSITIVE['declared_family']}）"
    )


# ---------------------------------------------------------------------------
# --regen：先跑 node 自省
# ---------------------------------------------------------------------------


def regenerate_introspection(out_dir: Path) -> int:
    if not INTROSPECT_ENTRY.is_file():
        log(f"REGEN FAIL：缺 {INTROSPECT_ENTRY.relative_to(REPO)} —— 先 pnpm --filter @wbtime/db run build")
        return EXIT_USAGE
    proc = subprocess.run(
        ["node", str(INTROSPECT_ENTRY), "--out", str(out_dir)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    for line in (proc.stdout or "").splitlines():
        log(f"  regen| {line}")
    if proc.returncode != 0:
        for line in (proc.stderr or "").splitlines():
            log(f"  regen! {line}")
        log(f"REGEN FAIL：node 自省退出码 {proc.returncode}")
        return EXIT_USAGE
    return EXIT_OK


# ---------------------------------------------------------------------------
# --self-test
# ---------------------------------------------------------------------------


def _clone(workdir: Path, pg_ddl: Path, sqlite_ddl: Path, pg_intro: Path, sqlite_intro: Path) -> tuple[Path, Path, Path, Path]:
    out = workdir / "output"
    out.mkdir(parents=True, exist_ok=True)
    pg_out = out / "ddl.pg.sql"
    sq_out = out / "ddl.sqlite.sql"
    pg_i = out / "drizzle-introspect.pg.json"
    sq_i = out / "drizzle-introspect.sqlite.json"
    shutil.copy2(pg_ddl, pg_out)
    shutil.copy2(sqlite_ddl, sq_out)
    shutil.copy2(pg_intro, pg_i)
    shutil.copy2(sqlite_intro, sq_i)
    return pg_out, sq_out, pg_i, sq_i


def _expect(rep: Report, label: str, kind: str, needle: str | None = None) -> bool:
    if not rep.has_kind(kind):
        log(f"  x {label}：期望出现 [{kind}]，实际没出现")
        return False
    if needle is not None and not (rep.from_contains(kind, needle) or rep.from_detail_contains(kind, needle)):
        log(f"  x {label}：出现了 [{kind}] 但不含 {needle}")
        return False
    log(f"  v {label}：[{kind}]" + (f" 含 {needle}" if needle else ""))
    return True


def _mutate_introspect(path: Path, mutate: Any) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_self_test(pg_ddl: Path, sqlite_ddl: Path, pg_intro: Path, sqlite_intro: Path) -> int:
    log("SELFTEST 开始（全部操作在临时目录，绝不动 contracts/ 与真实产物）")
    try:
        pg_doc = load_json(PG_CONTRACT)
        sqlite_doc = load_json(SQLITE_CONTRACT)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"SELFTEST FAIL: frozen 契约无法加载 —— {exc}")
        return EXIT_SELFTEST

    failures = 0
    with tempfile.TemporaryDirectory(prefix="drizzle-parity-st-") as tmp:
        root = Path(tmp)
        pg_view = contract_view(pg_doc)

        # 0) baseline 必须绿
        rep0, _ = collect(pg_ddl, sqlite_ddl, pg_intro, sqlite_intro, pg_doc, sqlite_doc)
        if rep0.diffs:
            log(f"SELFTEST FAIL [baseline]：未注入就已经红（{len(rep0.diffs)} 条）")
            for d in rep0.diffs[:10]:
                log(f"    {d.render()}")
            failures += 1
        else:
            log("  v baseline：未注入的产物是绿的")

        # 1) 少一表（自省侧删掉 task）
        pg1, sq1, pgi1, sqi1 = _clone(root / "c1", pg_ddl, sqlite_ddl, pg_intro, sqlite_intro)
        _mutate_introspect(pgi1, lambda doc: doc.update(tables=[t for t in doc["tables"] if t["name"] != "task"]))
        rep1, _ = collect(pg1, sq1, pgi1, sqi1, pg_doc, sqlite_doc)
        log("  case1 注入：从自省 JSON 删掉 task 表")
        if not _expect(rep1, "case1 少一表必红", "src.pg.table", "task"):
            failures += 1

        # 2) 少一列（自省侧删掉 document.checksum —— 正是首轮被误报的那一列）
        pg2, sq2, pgi2, sqi2 = _clone(root / "c2", pg_ddl, sqlite_ddl, pg_intro, sqlite_intro)

        def drop_checksum(doc: dict[str, Any]) -> None:
            for t in doc["tables"]:
                if t["name"] == "document":
                    t["columns"] = [c for c in t["columns"] if c["name"] != "checksum"]
                    doc["counts"]["columns"] = sum(len(x["columns"]) for x in doc["tables"])

        _mutate_introspect(pgi2, drop_checksum)
        rep2, _ = collect(pg2, sq2, pgi2, sqi2, pg_doc, sqlite_doc)
        log("  case2 注入：从自省 JSON 删掉 document.checksum 列")
        if not _expect(rep2, "case2 少一列必红", "src.pg.column", "document"):
            failures += 1
        if not _expect(rep2, "case2 列数必红", "src.pg.column-count"):
            failures += 1

        # 3) 少一外键（自省侧删掉 agent 的一条 FK）
        pg3, sq3, pgi3, sqi3 = _clone(root / "c3", pg_ddl, sqlite_ddl, pg_intro, sqlite_intro)

        def drop_fk(doc: dict[str, Any]) -> None:
            for t in doc["tables"]:
                if t["name"] == "agent":
                    t["foreign_keys"] = t["foreign_keys"][1:]
                    doc["counts"]["foreign_keys"] = sum(len(x["foreign_keys"]) for x in doc["tables"])

        _mutate_introspect(pgi3, drop_fk)
        rep3, _ = collect(pg3, sq3, pgi3, sqi3, pg_doc, sqlite_doc)
        log("  case3 注入：从自省 JSON 删掉 agent 的一条外键")
        if not _expect(rep3, "case3 少一外键必红", "src.pg.foreign-key", "agent"):
            failures += 1
        if not _expect(rep3, "case3 外键硬计数必红", "hard.pg.foreign_keys"):
            failures += 1

        # 4) 少一 hnsw（PG DDL 里删掉一条 USING hnsw）
        pg4, sq4, pgi4, sqi4 = _clone(root / "c4", pg_ddl, sqlite_ddl, pg_intro, sqlite_intro)
        text4 = pg4.read_text(encoding="utf-8")
        hnsw_lines = [line for line in text4.splitlines() if "USING hnsw" in line]
        if len(hnsw_lines) != 2:
            log(f"  x case4 前置异常：USING hnsw 行数={len(hnsw_lines)}（应为 2）")
            failures += 1
        else:
            pg4.write_text(text4.replace(hnsw_lines[1] + "\n", ""), encoding="utf-8")
            rep4, _ = collect(pg4, sq4, pgi4, sqi4, pg_doc, sqlite_doc)
            log("  case4 注入：删除第 2 条 USING hnsw 索引（仅 PG 档 DDL）")
            if not _expect(rep4, "case4 hnsw 数量硬断言", "pg.hnsw-count"):
                failures += 1
            dropped = pg_view["raw_indexes"][1]["name"]
            if not _expect(rep4, "case4 hnsw 名字缺失", "pg.hnsw-name", dropped):
                failures += 1

        # 5) 空集合（DDL 表体清空 + 自省 tables 清空）
        pg5, sq5, pgi5, sqi5 = _clone(root / "c5", pg_ddl, sqlite_ddl, pg_intro, sqlite_intro)
        head = "-- ===== 2. 表与所属索引（按表名排序）====="
        pg5.write_text(f"-- truncated by self-test\n\n{head}\n", encoding="utf-8")
        _mutate_introspect(pgi5, lambda doc: doc.update(tables=[]))
        rep5, _ = collect(pg5, sq5, pgi5, sqi5, pg_doc, sqlite_doc)
        log("  case5 注入：PG DDL 表体清空 + 自省 tables 清空")
        if not _expect(rep5, "case5 空集合必红（DDL）", "pg.EMPTY"):
            failures += 1
        if not _expect(rep5, "case5 空集合必红（自省）", "src.pg.EMPTY"):
            failures += 1
        if not _expect(rep5, "case5 hnsw 归零必红", "pg.hnsw-count"):
            failures += 1

        # 6) 陈旧自省（改 schema 哈希）
        pg6, sq6, pgi6, sqi6 = _clone(root / "c6", pg_ddl, sqlite_ddl, pg_intro, sqlite_intro)

        def poison_digest(doc: dict[str, Any]) -> None:
            doc["source"]["files"][0]["sha256"] = "0" * 64

        _mutate_introspect(pgi6, poison_digest)
        rep6, _ = collect(pg6, sq6, pgi6, sqi6, pg_doc, sqlite_doc)
        log("  case6 注入：篡改自省 JSON 里某个 .ts 的 sha256")
        if not _expect(rep6, "case6 陈旧自省必红", "src.stale"):
            failures += 1

    if failures:
        log(f"SELFTEST VERDICT: FAIL（{failures} 条断言未成立）")
        return EXIT_SELFTEST
    log("SELFTEST VERDICT: PASS（6 次注入都按预期理由变红，baseline 保持绿）")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_drizzle_parity.py",
        description="DoD#1/#2：Drizzle（TS）数据层 + 双档 DDL 与冻结契约 v0018 的 parity 门禁",
    )
    parser.add_argument("--pg-ddl", type=Path, default=DEFAULT_PG_DDL, help="生成的 PG DDL 路径")
    parser.add_argument("--sqlite-ddl", type=Path, default=DEFAULT_SQLITE_DDL, help="生成的 SQLite DDL 路径")
    parser.add_argument("--introspect-dir", type=Path, default=DEFAULT_INTROSPECT_DIR, help="自省 JSON 所在目录")
    parser.add_argument("--regen", action="store_true", help="先跑 node 自省（需 pnpm install + build）再校验")
    parser.add_argument("--self-test", action="store_true", help="注入反例并断言必红（不动真实 contracts/）")
    parser.add_argument("--json", type=Path, default=None, help="把 diff 结果另存为 JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pg_intro = args.introspect_dir / "drizzle-introspect.pg.json"
    sqlite_intro = args.introspect_dir / "drizzle-introspect.sqlite.json"

    if args.regen:
        code = regenerate_introspection(args.introspect_dir)
        if code != EXIT_OK:
            return code

    if args.self_test:
        for needed in (args.pg_ddl, args.sqlite_ddl, pg_intro, sqlite_intro):
            if not needed.is_file():
                log(f"SELFTEST FAIL: 缺产物 {needed} —— 先跑 node scripts/gen-ddl.ts 与自省")
                return EXIT_USAGE
        return run_self_test(args.pg_ddl, args.sqlite_ddl, pg_intro, sqlite_intro)

    try:
        pg_doc = load_json(PG_CONTRACT)
        sqlite_doc = load_json(SQLITE_CONTRACT)
        rep, stats = collect(args.pg_ddl, args.sqlite_ddl, pg_intro, sqlite_intro, pg_doc, sqlite_doc)
    except FileNotFoundError as exc:
        log(f"USAGE/LOAD FAIL: {exc}")
        return EXIT_USAGE
    except (json.JSONDecodeError, ValueError) as exc:
        log(f"USAGE/LOAD FAIL: 产物解析失败 —— {exc}")
        return EXIT_USAGE

    print_report(stats)

    log("-" * 74)
    if not rep.diffs:
        log("VERDICT: PASS —— DDL / 运行时自省 / 冻结契约 三方零差异（离线 parity）")
        log("注意：本门禁是**文本与结构 ↔ 冻结文本**的离线比对；本机无 psql / SSH 不通，")
        log("      故 PG 档**未**获得权威实例验证，不得据此记为 PG 档运行时 PASS。")
        for line in rep.info:
            log(f"  {line}")
        return EXIT_OK

    log(f"VERDICT: FAIL —— {len(rep.diffs)} 条差异")
    for d in rep.diffs[:60]:
        log(f"  {d.render()}")
    if len(rep.diffs) > 60:
        log(f"  …（共 {len(rep.diffs)} 条，已截断至前 60 条）")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                [{"kind": d.kind, "subject": d.subject, "detail": d.detail} for d in rep.diffs],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log(f"diff 已写入 {args.json}")
    return EXIT_VIOLATION


if __name__ == "__main__":
    raise SystemExit(main())
