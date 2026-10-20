"""DDL 冻结面**三源合并**抽取核心（C-03）。

三个来源不是可选项，缺一源即冻结面失真（路线图 §3.3.1 / M-02）：

源① ``ORM metadata`` 编译
    61 张表 / 174 个索引（``unique`` 7 / ``partial`` 1）。常规对象的**唯一**来源。
    类型一律以 **PG 方言真正 emit 出来的类型**为准（``UUID`` 而非声明名 ``CHAR(36)``，
    ``TIMESTAMP WITH TIME ZONE`` 而非 ``DATETIME``）——M-01。

源② 迁移链 **raw DDL**（``migrations/versions/*.py`` 里的 ``op.execute`` 字符串）
    ``ix_embedding_vector_hnsw`` / ``ix_memory_vector_hnsw`` 两个 ``USING hnsw`` 向量索引。
    ``Base.metadata`` **表达不了**它们，纯 ORM 编译路线会**静默漏掉**
    （实测：metadata 编译结果里 ``hnsw`` 出现 0 次）。

源③ **SQLite 专属对象**
    ``document_chunk_fts`` FTS5 虚表 + 影子表 + ``ai``/``ad``/``au`` 三个同步触发器。
    PG DDL 里 0 处；只取 PG 会让社区默认档（SQLite）的全文检索能力丢失且无人察觉。

本模块只做**纯函数式**抽取与渲染：不写文件、不读环境变量，便于单测与 ``--check`` 复用。
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite as sqlite_dialect_module
from sqlalchemy.schema import CreateIndex, CreateTable

__all__ = [
    "PG_DIALECT",
    "SQLITE_DIALECT",
    "RawStatement",
    "SqliteOnlyObject",
    "build_pg_snapshot",
    "build_sqlite_snapshot",
    "dump_json",
    "extract_raw_statements",
    "materialize_fts5_objects",
    "render_pg_sql",
    "render_sqlite_sql",
]

#: 复用方言实例：``dialect.type_compiler`` 内部有缓存，重复构造会拖慢 629 列的编译。
PG_DIALECT = postgresql.dialect()
SQLITE_DIALECT = sqlite_dialect_module.dialect()

#: 「表名 + 索引」段落的分隔说明宽度（纯排版，不影响内容）。
_RULE = "=" * 78


def _quote(dialect: Any, identifier: str | None) -> str:
    """按方言规则引用标识符（保留字如 ``metadata`` / ``order`` 必须加引号）。

    Raises:
        ValueError: ``identifier`` 为 ``None``（调用方必须先决定如何处理无名对象）。
    """
    if identifier is None:
        raise ValueError("cannot quote a None identifier")
    return dialect.identifier_preparer.quote(identifier)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RawStatement:
    """从迁移文件里原样提取出的一条 raw SQL 语句。

    Attributes:
        name: 对象名（索引 / 虚表 / 触发器 / 扩展）。
        kind: ``index`` | ``extension`` | ``virtual_table`` | ``trigger``。
        sql: 规范化空白后的 SQL 原文（**不含**结尾分号）。
        origin: 溯源串 ``<相对路径>:<行号>``。
        table: 所属表名（可空）。
    """

    name: str
    kind: str
    sql: str
    origin: str
    table: str | None


@dataclasses.dataclass(frozen=True)
class SqliteOnlyObject:
    """SQLite 方言专属对象（虚表 / 影子表 / 触发器）。

    Attributes:
        name: 对象名。
        kind: ``virtual_table`` | ``shadow_table`` | ``trigger``。
        sql: 该对象在 ``sqlite_master`` 里的建对象语句（真实由 SQLite 生成）。
        origin: 溯源串。
        table: 直属表（影子表为虚表名，触发器为 ``document_chunk``）。
    """

    name: str
    kind: str
    sql: str
    origin: str
    table: str | None


# ---------------------------------------------------------------------------
# 源②/③：AST 提取迁移链 raw DDL
# ---------------------------------------------------------------------------


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """收集模块级 ``_NAME = "literal"`` 常量，供 f-string 求值使用。"""
    constants: dict[str, str] = {}

    def _record(target: ast.expr, value: ast.expr) -> None:
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            constants[target.id] = value.value

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            _record(node.targets[0], node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _record(node.target, node.value)
    return constants


def _render_string_node(node: ast.expr, constants: dict[str, str]) -> str | None:
    """把「常量 / f-string / 相邻字面量拼接」的表达式还原成字符串。

    迁移文件里 ``op.execute`` 的实参**始终**是编译期可求值的形状：

    * ``"CREATE INDEX x ON y ..."``（``ast.Constant``）
    * ``f"CREATE INDEX {_HNSW_INDEX_NAME} ON embedding " "USING hnsw ..."``
      （``ast.JoinedStr`` + 相邻 ``Constant`` 的隐式拼接）
    * ``"a" "b"``（编译器已合并，仍是 ``Constant``）

    因此不需要执行模块（避免副作用），纯语法求值即可。

    Args:
        node: 实参表达式节点。
        constants: 模块级字符串常量表。

    Returns:
        还原后的字符串；形状不可静态求值时返回 ``None``（调用方跳过并告警）。
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                if value.value.id not in constants:
                    return None
                parts.append(constants[value.value.id])
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _render_string_node(node.left, constants)
        right = _render_string_node(node.right, constants)
        if left is None or right is None:
            return None
        return left + right
    return None


def _normalize_sql(text: str) -> str:
    """折叠空白与换行，去掉结尾分号（渲染时统一再加），保证跨平台稳定。"""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed.rstrip(";").strip()


_INDEX_RE = re.compile(
    r"create\s+index\s+(?:if\s+not\s+exists\s+)?([\w\"\.]+)\s+on\s+([\w\"\.]+)",
    re.IGNORECASE,
)
_VIRTUAL_TABLE_RE = re.compile(
    r"create\s+virtual\s+table\s+(?:if\s+not\s+exists\s+)?([\w\"\.]+)", re.IGNORECASE
)
_TRIGGER_RE = re.compile(r"create\s+trigger\s+(?:if\s+not\s+exists\s+)?([\w\"\.]+)", re.IGNORECASE)
_EXTENSION_RE = re.compile(r"create\s+extension\s+(?:if\s+not\s+exists\s+)?([\w\"\.]+)", re.IGNORECASE)


def _unquote(identifier: str) -> str:
    """去掉标识符两端的双引号/反引号/方括号。"""
    return identifier.strip().strip('"`[]')


def _classify(sql: str) -> tuple[str, str, str | None] | None:
    """判定一条 raw SQL 属于哪一类方言专属对象。

    Args:
        sql: 规范化后的 SQL。

    Returns:
        ``(kind, name, table)``；不属于三类方言专属对象时返回 ``None``（例如业务 DML / DDL
        已经在 metadata 里，参与三源合并会**重复计数**）。
    """
    lowered = sql.lower()
    if "using hnsw" in lowered:
        match = _INDEX_RE.search(sql)
        if match is None:
            return None
        return ("index", _unquote(match.group(1)), _unquote(match.group(2)))
    match = _EXTENSION_RE.search(sql)
    if match is not None and lowered.startswith("create extension"):
        return ("extension", _unquote(match.group(1)), None)
    match = _VIRTUAL_TABLE_RE.search(sql)
    if match is not None:
        return ("virtual_table", _unquote(match.group(1)), None)
    match = _TRIGGER_RE.search(sql)
    if match is not None:
        target = re.search(r"\bon\s+([\w\"\.]+)", sql, re.IGNORECASE)
        return ("trigger", _unquote(match.group(1)), _unquote(target.group(1)) if target else None)
    return None


def extract_raw_statements(source_root: str | Path) -> list[RawStatement]:
    """扫描 ``migrations/versions/*.py``，提取全部方言专属 raw SQL 语句。

    Args:
        source_root: 旧仓根目录（盘符形式）。

    Returns:
        按 ``(kind, name)`` 稳定排序的语句列表。

    Raises:
        FileNotFoundError: 迁移目录不存在（说明 ``--source`` 指错了仓）。
    """
    root = Path(source_root)
    versions = root / "migrations" / "versions"
    if not versions.is_dir():
        raise FileNotFoundError(f"迁移目录不存在：{versions}")

    collected: list[RawStatement] = []
    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        constants = _string_constants(tree)
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in {"execute", "exec_driver_sql"}:
                continue
            if not node.args:
                continue
            rendered = _render_string_node(node.args[0], constants)
            if rendered is None:
                continue
            sql = _normalize_sql(rendered)
            classified = _classify(sql)
            if classified is None:
                continue
            kind, name, table = classified
            collected.append(
                RawStatement(
                    name=name,
                    kind=kind,
                    sql=sql,
                    origin=f"{relative}:{node.lineno}",
                    table=table,
                )
            )
    ordered = sorted(collected, key=lambda item: (item.kind, item.name, item.origin))
    return ordered


_EXTERNAL_CONTENT_RE = re.compile(r"content\s*=\s*'([^']+)'", re.IGNORECASE)
_NEW_OLD_COLUMN_RE = re.compile(r"\b(?:new|old)\.([A-Za-z_]\w*)", re.IGNORECASE)


def _stub_external_content_table(
    connection: sqlite3.Connection,
    virtual_sql: str,
    trigger_sqls: Sequence[str],
) -> str | None:
    """为 external-content FTS5 虚表建一张**占位内容表**。

    FTS5 的 ``content='<table>'`` 模式在 ``CREATE VIRTUAL TABLE`` 时会校验内容表存在，
    否则直接报 ``no such table: main.document_chunk``。影子表的定义与内容表的数据无关，
    因此这里只需建一张含触发器中引用列（``new.content`` 等）的占位表即可让 SQLite
    生成**完全一致**的影子表结构。

    Args:
        connection: 内存 SQLite 连接。
        virtual_sql: ``CREATE VIRTUAL TABLE ...`` 语句。
        trigger_sqls: 触发器语句（提供引用列清单）。

    Returns:
        占位表名；非 external-content 模式返回 ``None``。
    """
    match = _EXTERNAL_CONTENT_RE.search(virtual_sql)
    if match is None:
        return None
    content_table = match.group(1)
    referenced: list[str] = []
    for sql in trigger_sqls:
        for column in _NEW_OLD_COLUMN_RE.findall(sql):
            if column.lower() != "rowid" and column not in referenced:
                referenced.append(column)
    if not referenced:
        referenced = ["content"]
    columns = ", ".join(f"{_quote(SQLITE_DIALECT, name)} TEXT" for name in referenced)
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {_quote(SQLITE_DIALECT, content_table)} ({columns})"
    )
    return content_table


def materialize_fts5_objects(raw_statements: Sequence[RawStatement]) -> list[SqliteOnlyObject]:
    """在内存 SQLite 里**真建** FTS5 虚表，再从 ``sqlite_master`` 读出影子表定义。

    影子表（``_data`` / ``_idx`` / ``_docsize`` / ``_config``）由 SQLite 内部生成，**任何源
    文件里都没有它们的 DDL**；唯一可信的取法是让 SQLite 自己建一遍再读出来。
    注意 external-content 模式（``content='document_chunk'``）**不会**生成 ``_content``
    影子表——这一点与文档记载的「5 张影子表」不符，以实测为准（见 ``ddl/README.md``）。

    Args:
        raw_statements: :func:`extract_raw_statements` 的结果。

    Returns:
        按 ``(kind 顺序, name)`` 稳定排序的 SQLite 专属对象列表。

    Raises:
        RuntimeError: 迁移里没有 FTS5 虚表语句，或虚表建表失败。
    """
    virtuals = [s for s in raw_statements if s.kind == "virtual_table"]
    if not virtuals:
        raise RuntimeError("迁移链里没有找到 CREATE VIRTUAL TABLE 语句（FTS5 源③ 缺失）")
    triggers = [s for s in raw_statements if s.kind == "trigger"]

    connection = sqlite3.connect(":memory:")
    try:
        for statement in virtuals:
            _stub_external_content_table(
                connection, statement.sql, [item.sql for item in triggers]
            )
            connection.execute(statement.sql)
        for statement in triggers:
            connection.execute(statement.sql)
        connection.commit()
        fts_names = [item.name for item in virtuals]
        rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()

    objects: list[SqliteOnlyObject] = []
    trigger_names = {item.name for item in triggers}
    for type_, name, table, sql in rows:
        if sql is None:
            continue
        is_fts = (
            name in fts_names
            or name in trigger_names
            or any(name.startswith(f"{base}_") for base in fts_names)
        )
        if not is_fts:
            continue
        if type_ == "table":
            kind = "virtual_table" if name in fts_names else "shadow_table"
        elif type_ == "trigger":
            kind = "trigger"
        else:
            kind = type_
        origin = "sqlite_master（执行 0013 FTS5 语句后回读）"
        objects.append(
            SqliteOnlyObject(name=name, kind=kind, sql=_normalize_sql(sql), origin=origin, table=table)
        )

    kind_order = {"virtual_table": 0, "shadow_table": 1, "trigger": 2}
    return sorted(objects, key=lambda item: (kind_order.get(item.kind, 9), item.name))


# ---------------------------------------------------------------------------
# 快照归一化
# ---------------------------------------------------------------------------


def _default_text(column: Any, dialect: Any) -> str | None:
    """把列的 ``server_default`` 编译成该方言下的字面文本（无默认值返回 ``None``）。"""
    default = column.server_default
    if default is None:
        return None
    argument = getattr(default, "arg", None)
    if argument is None:
        return None
    compile_ = getattr(argument, "compile", None)
    if compile_ is None:
        return str(argument)
    return str(compile_(dialect=dialect, compile_kwargs={"literal_binds": True}))


def _index_expression_text(expression: Any, dialect: Any) -> str:
    """索引列表达式 → 文本（普通列取列名；表达式索引取编译结果）。"""
    if hasattr(expression, "name") and getattr(expression, "table", None) is not None:
        return str(expression.name)
    return str(expression.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def _index_where_text(index: Any, dialect_name: str) -> str | None:
    """取部分索引（partial index）的 WHERE 子句文本。

    Args:
        index: ``sqlalchemy.Index``。
        dialect_name: ``"postgresql"`` 或 ``"sqlite"``。

    Returns:
        WHERE 子句正文（不含 ``WHERE`` 关键字）；非部分索引返回 ``None``。
    """
    options = index.dialect_options.get(dialect_name, {}) or {}
    where = options.get("where")
    if where is None:
        return None
    text = getattr(where, "text", None)
    if text is not None:
        return str(text)
    return str(where.compile(dialect=PG_DIALECT, compile_kwargs={"literal_binds": True}))


def _index_entry(index: Any, dialect: Any, dialect_name: str) -> dict[str, Any]:
    """索引 → 归一化条目（``columns`` 用真实列序，``where`` 用该方言的子句）。"""
    return {
        "name": index.name,
        "columns": [_index_expression_text(expression, dialect) for expression in index.expressions],
        "unique": bool(index.unique),
        "where": _index_where_text(index, dialect_name),
    }


def _foreign_key_entry(constraint: Any) -> dict[str, Any]:
    """外键约束 → 归一化条目（列序与目标列序保持一致）。"""
    return {
        "name": constraint.name,
        "columns": [element.parent.name for element in constraint.elements],
        "referred_table": constraint.referred_table.name,
        "referred_columns": [element.column.name for element in constraint.elements],
        "ondelete": constraint.ondelete,
        "onupdate": constraint.onupdate,
    }


def _unique_sort_key(constraint: Any) -> tuple[str, tuple[str, ...]]:
    """UNIQUE 约束的全序排序键（无名约束用列名兜底，避免集合迭代序影响 diff）。"""
    return (
        constraint.name or "",
        tuple(column.name for column in constraint.columns),
    )


def _foreign_key_sort_key(constraint: Any) -> tuple[str, tuple[str, ...], str]:
    """外键的全序排序键（``name`` 可能为 ``None``，必须用列名做第二排序键）。"""
    return (
        constraint.name or "",
        tuple(element.parent.name for element in constraint.elements),
        constraint.referred_table.name,
    )


def _index_sort_key(index: Any) -> tuple[str, tuple[str, ...]]:
    """索引的全序排序键（同类名冲突时按列兜底）。"""
    columns = tuple(
        expression.name if hasattr(expression, "name") else str(expression)
        for expression in index.expressions
    )
    return (index.name or "", columns)


def _table_entry(table: Any, dialect: Any, dialect_name: str) -> dict[str, Any]:
    """表 → 归一化条目（列按定义序、索引按名称序，保证可稳定 diff）。"""
    return {
        "name": table.name,
        "columns": [
            {
                "name": column.name,
                "type": column.type.compile(dialect=dialect),
                "nullable": bool(column.nullable),
                "default": _default_text(column, dialect),
            }
            for column in table.columns
        ],
        "primary_key": [column.name for column in table.primary_key.columns],
        "unique_constraints": sorted(
            [
                {
                    "name": constraint.name,
                    "columns": [column.name for column in constraint.columns],
                }
                for constraint in table.constraints
                if type(constraint).__name__ == "UniqueConstraint"
            ],
            key=lambda item: (item["name"] or "", tuple(item["columns"])),
        ),
        "foreign_keys": sorted(
            [_foreign_key_entry(constraint) for constraint in table.foreign_key_constraints],
            key=lambda item: (item["name"] or "", tuple(item["columns"]), item["referred_table"]),
        ),
        "indexes": [
            _index_entry(index, dialect, dialect_name)
            for index in sorted(table.indexes, key=_index_sort_key)
        ],
    }


def _metadata_counts(
    metadata: MetaData, tables: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """metadata 侧计数（数字一律来自实跑，不写死）

    返回 ``dict[str, Any]`` 而非 ``dict[str, int]``：调用方会往里塞
    ``dialect_only_by_kind``（嵌套 dict），用 ``int`` 收窄会让 mypy 报 ``dict-item``。
    """
    metadata_indexes = [index for table in metadata.tables.values() for index in table.indexes]
    return {
        "tables": len(tables),
        "columns": sum(len(table["columns"]) for table in tables),
        "metadata_indexes": len(metadata_indexes),
        "unique_indexes": sum(1 for index in metadata_indexes if index.unique),
        "partial_indexes": sum(
            1
            for index in metadata_indexes
            if _index_where_text(index, "postgresql") is not None
            or _index_where_text(index, "sqlite") is not None
        ),
        "unique_constraints": sum(
            1
            for table in metadata.tables.values()
            for constraint in table.constraints
            if type(constraint).__name__ == "UniqueConstraint"
        ),
        "foreign_keys": sum(
            len(table.foreign_key_constraints) for table in metadata.tables.values()
        ),
    }


def _hnsw_entry(statement: RawStatement) -> dict[str, Any]:
    """把一个 ``USING hnsw`` 语句解析成结构化条目（供 normalized JSON 与对账使用）。"""
    method_match = re.search(r"using\s+(\w+)\s*\(\s*([\w\"]+)\s+([\w_]+)\s*\)", statement.sql, re.IGNORECASE)
    options_match = re.search(r"with\s*\(([^)]*)\)", statement.sql, re.IGNORECASE)
    options: dict[str, str] = {}
    if options_match is not None:
        for chunk in options_match.group(1).split(","):
            key, _, value = chunk.partition("=")
            if key.strip():
                options[key.strip()] = value.strip()
    return {
        "name": statement.name,
        "table": statement.table,
        "method": (method_match.group(1) if method_match else "hnsw").lower(),
        "indexed_column": method_match.group(2) if method_match else None,
        "operator_class": method_match.group(3) if method_match else None,
        "options": options,
        "sql": f"{statement.sql};",
        "source": f"migration:{statement.origin}",
    }


_TRIGGER_SHAPE_RE = re.compile(
    r"^CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\"\.]+)\s+"
    r"(BEFORE|AFTER|INSTEAD\s+OF)\s+(INSERT|UPDATE|DELETE)\s+ON\s+([\w\"\.]+)\s+"
    r"BEGIN\s+(.*?)\s*END$",
    re.IGNORECASE | re.DOTALL,
)


def _trigger_entry(item: SqliteOnlyObject) -> dict[str, Any]:
    """触发器 → 结构化条目（``timing`` / ``event`` / ``body`` 从 SQL 原文解析）。

    🔴 FTS5 ``external content`` 模式下，**没有这三个触发器，FTS 索引不会随基表变更更新**
    ——全文检索会静默失真。它们是功能性对象，不是装饰对象。

    Args:
        item: 由 :func:`materialize_fts5_objects` 产出的触发器对象。

    Returns:
        含 ``name`` / ``table`` / ``timing`` / ``event`` / ``body`` / ``body_sha256`` /
        ``sql`` / ``source`` 的 dict；形状不可解析时 ``timing`` / ``event`` / ``body`` 为 ``None``
        （``sql`` 始终保留原文，不会丢信息）。
    """
    match = _TRIGGER_SHAPE_RE.match(item.sql)
    body = match.group(5) if match else None
    return {
        "name": item.name,
        "table": (match.group(4) if match else None) or item.table,
        "timing": match.group(2).upper() if match else None,
        "event": match.group(3).upper() if match else None,
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if body else None,
        "sql": f"{item.sql};",
        "source": item.origin,
    }


def _group_extensions(raw_statements: Sequence[RawStatement]) -> list[dict[str, Any]]:
    """把 ``CREATE EXTENSION`` 按 SQL 原文去重聚合（0013 / 0014 各写一次，语句幂等）。

    去重是**可读性**处理，不丢溯源：``sources`` 保留每一处出现的位置，计数另有
    ``extension_statements``（去重前的语句条数）。

    Args:
        raw_statements: 迁移链 raw 语句。

    Returns:
        形如 ``{"name", "sql", "sources"}`` 的列表（按 name 排序）。
    """
    grouped: dict[str, dict[str, Any]] = {}
    for statement in raw_statements:
        if statement.kind != "extension":
            continue
        entry = grouped.setdefault(
            statement.sql,
            {"name": statement.name, "sql": f"{statement.sql};", "sources": []},
        )
        entry["sources"].append(f"migration:{statement.origin}")
    return [grouped[key] for key in sorted(grouped, key=lambda sql: grouped[sql]["name"])]


def build_pg_snapshot(
    metadata: MetaData,
    raw_statements: Sequence[RawStatement],
) -> dict[str, Any]:
    """合成 **PG 侧** normalized 快照（源① + 源②）。

    Args:
        metadata: ORM metadata（61 表）。
        raw_statements: 迁移链 raw 语句（含 2 个 hnsw + ``CREATE EXTENSION``）。

    Returns:
        稳定键序的 dict，可直接 ``json.dumps`` 落盘。
    """
    tables = [
        _table_entry(table, PG_DIALECT, "postgresql")
        for table in sorted(metadata.tables.values(), key=lambda item: item.name)
    ]
    counts = _metadata_counts(metadata, tables)
    raw_indexes = [
        _hnsw_entry(statement)
        for statement in sorted(raw_statements, key=lambda item: item.name)
        if statement.kind == "index"
    ]
    extensions = _group_extensions(raw_statements)
    counts.update(
        {
            "raw_indexes": len(raw_indexes),
            "index_objects_total": counts["metadata_indexes"] + len(raw_indexes),
            "extensions": len(extensions),
            "extension_statements": sum(
                len(extension["sources"]) for extension in extensions
            ),
            "dialect_only_objects": len(raw_indexes),
            "dialect_only_by_kind": {"index": len(raw_indexes)},
            "triggers": 0,
        }
    )
    return {
        "dialect": "postgresql",
        "schema_version": "v0018",
        "frozen_contract": "V0.0.1 / C-03",
        "generated_by": "scripts/extract-from-py/ddl/export_ddl.py",
        "counts": counts,
        "tables": tables,
        "raw_indexes": raw_indexes,
        "extensions": extensions,
        "triggers": [],
        "dialect_only": [],
        "notes": [
            (
                "类型为 PG 方言真正 emit 的类型（UUID / TIMESTAMP WITH TIME ZONE / JSONB / VECTOR），"
                "不是 str(col.type) 的声明名（M-01）"
            ),
            "raw_indexes 来自迁移链 raw DDL：Base.metadata 无法表达 hnsw，纯 ORM 编译会静默漏掉",
            "unique_indexes 与 unique_constraints 是两个不同集合，勿混算进索引数",
            "PG 侧 DB 触发器为 0：三个 FTS5 同步触发器是 SQLite 专属（dialect_only: sqlite）",
        ],
    }


def build_sqlite_snapshot(
    metadata: MetaData,
    sqlite_only_objects: Sequence[SqliteOnlyObject],
) -> dict[str, Any]:
    """合成 **SQLite 侧** normalized 快照（源① + 源③）。

    Args:
        metadata: ORM metadata（61 表）。
        sqlite_only_objects: 由 :func:`materialize_fts5_objects` 产出的 FTS5 相关对象。

    Returns:
        与 PG 快照**同构**的 dict（顶层键完全一致，便于 diff 两份快照）。
    """
    tables = [
        _table_entry(table, SQLITE_DIALECT, "sqlite")
        for table in sorted(metadata.tables.values(), key=lambda item: item.name)
    ]
    counts = _metadata_counts(metadata, tables)
    by_kind: dict[str, int] = {}
    for item in sqlite_only_objects:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
    triggers = [_trigger_entry(item) for item in sqlite_only_objects if item.kind == "trigger"]
    counts.update(
        {
            "raw_indexes": 0,
            "index_objects_total": counts["metadata_indexes"],
            "extensions": 0,
            "dialect_only_objects": len(sqlite_only_objects),
            "dialect_only_by_kind": dict(sorted(by_kind.items())),
            "triggers": len(triggers),
            "virtual_tables": by_kind.get("virtual_table", 0),
            "shadow_tables": by_kind.get("shadow_table", 0),
        }
    )
    return {
        "dialect": "sqlite",
        "schema_version": "v0018",
        "frozen_contract": "V0.0.1 / C-03",
        "generated_by": "scripts/extract-from-py/ddl/export_ddl.py",
        "counts": counts,
        "tables": tables,
        "raw_indexes": [],
        "extensions": [],
        "triggers": triggers,
        "dialect_only": [
            {"kind": item.kind, "name": item.name, "table": item.table, "sql": f"{item.sql};", "source": item.origin}
            for item in sqlite_only_objects
        ],
        "notes": [
            "类型为 SQLite 方言真正 emit 的类型（CHAR(36) / DATETIME / JSON）",
            "hnsw 系 PG 专属（pgvector），SQLite 侧**不存在**：属合法 dialect_only 差异，不是遗漏",
            "FTS5 影子表由 SQLite 内部生成，源文件里没有它们的 DDL，故在内存库真建一遍后回读 sqlite_master",
            (
                "外部内容模式（content='document_chunk'）不生成 _content 影子表：实测影子表 "
                "4 张（_config/_data/_docsize/_idx），文档「5 张」口径错误，不得为凑数臆造 _content"
            ),
            (
                "FTS5 同步触发器 3 个（document_chunk_ai/ad/au）为**功能性对象**："
                "external content 模式下缺了它们，FTS 索引不会随基表变更更新，全文检索静默失真"
            ),
            "表级 UNIQUE 约束会由 SQLite 自动建 sqlite_autoindex_*，不入冻结计数（隐式对象）",
        ],
    }


# ---------------------------------------------------------------------------
# SQL 渲染
# ---------------------------------------------------------------------------


def _terminate(statement: str) -> str:
    """补齐单条语句的结尾分号（内部已去掉，避免出现 ``;;``）。"""
    return statement.strip().rstrip(";").strip() + ";"


def _alter_add_foreign_key(table_name: str, constraint: Any, dialect: Any) -> str:
    """渲染 ``ALTER TABLE ... ADD [CONSTRAINT name] FOREIGN KEY``（PG 用）。

    少数外键在模型里没有显式名字（``constraint.name is None``）；此时**不臆造名字**，
    渲染成无名约束——``normalized.json`` 里同样记 ``name: null``，两侧口径一致。
    """
    columns = ", ".join(_quote(dialect, element.parent.name) for element in constraint.elements)
    referred = ", ".join(_quote(dialect, element.column.name) for element in constraint.elements)
    named = (
        f"ADD CONSTRAINT {_quote(dialect, constraint.name)} FOREIGN KEY"
        if constraint.name
        else "ADD FOREIGN KEY"
    )
    clauses = [
        f"ALTER TABLE {_quote(dialect, table_name)}",
        f"{named} ({columns})",
        f"REFERENCES {_quote(dialect, constraint.referred_table.name)} ({referred})",
    ]
    if constraint.ondelete:
        clauses.append(f"ON DELETE {constraint.ondelete}")
    if constraint.onupdate:
        clauses.append(f"ON UPDATE {constraint.onupdate}")
    return " ".join(clauses)


def _header_lines(title: str, snapshot: dict[str, Any], preamble: Sequence[str]) -> list[str]:
    """生成文件头注释块（数字全部取自本次实跑，杜绝手写漂移）。"""
    counts = snapshot["counts"]
    lines = [
        "-- " + _RULE,
        f"-- {title}",
        "-- " + _RULE,
        f"-- 契约版本：schema_version = {snapshot['schema_version']}（对应迁移链 0018 收敛态）",
        f"-- 方言：{snapshot['dialect']}",
        f"-- 生成者：{snapshot['generated_by']}（禁止手改；数字由脚本实跑得出）",
        "--",
        "-- 三源构成（缺一源即冻结面失真，路线图 §3.3.1 / M-02）：",
        (
            f"--   源① ORM metadata 编译：{counts['tables']} 表 / {counts['columns']} 列 / "
            f"{counts['metadata_indexes']} 索引"
            f"（unique {counts['unique_indexes']} / partial {counts['partial_indexes']}）"
        ),
    ]
    if snapshot["dialect"] == "postgresql":
        lines.append(
            f"--   源② 迁移链 raw DDL：{counts['raw_indexes']} 个 hnsw 向量索引"
            "（ix_embedding_vector_hnsw / ix_memory_vector_hnsw，metadata 里 0 处）"
        )
        lines.append(
            f"--   合并后索引对象总数：{counts['metadata_indexes']} + {counts['raw_indexes']} = "
            f"{counts['index_objects_total']}"
        )
    else:
        lines.append("--   源② 迁移链 raw DDL：0 个（hnsw 为 PG 专属，SQLite 侧不存在——合法差异）")
        by_kind = counts.get("dialect_only_by_kind", {})
        lines.append(
            "--   源③ SQLite 专属（共 "
            f"{counts['dialect_only_objects']} 个对象，PG DDL 里 0 处）："
            f"FTS5 虚表 ×{by_kind.get('virtual_table', 0)}"
            f" + 影子表 ×{by_kind.get('shadow_table', 0)}"
            f" + 同步触发器 ×{by_kind.get('trigger', 0)}"
        )
        lines.append(
            "--        触发器不是装饰对象：external content 模式下缺 ai/ad/au，"
            "FTS 索引不随基表更新，全文检索静默失真"
        )
    lines.append("--")
    for extra in preamble:
        lines.append(f"-- {extra}")
    lines.append("-- " + _RULE)
    lines.append("")
    return lines


def render_pg_sql(metadata: MetaData, snapshot: dict[str, Any]) -> str:
    """渲染 PG 侧完整 DDL（表按名称排序；外键延后为 ALTER，保证文件可执行）。

    Args:
        metadata: ORM metadata。
        snapshot: :func:`build_pg_snapshot` 的产物（数字来自它，保证头注释与内容一致）。

    Returns:
        以 ``\\n`` 结尾的 SQL 文本。
    """
    counts = snapshot["counts"]
    lines = _header_lines(
        "WBTimeAI DDL 冻结面 · PostgreSQL（schema v0018）",
        snapshot,
        [
            "段落顺序：1) 扩展 → 2) 表 + 所属索引（按表名排序）→ 3) 外键约束 → 4) 迁移 raw 索引",
            "外键延后到建表之后：这样「按表名排序」与「整份文件可执行」可以同时成立",
            "索引一律 FOLLOW 所属表，便于逐表对账；文件名序 = 冻结序（stable diff）",
        ],
    )

    lines.append("-- ===== 1. 扩展（源②：迁移 0013 _try_enable_pg_vector，raw DDL）=====")
    for extension in snapshot["extensions"]:
        for source in extension["sources"]:
            lines.append(f"-- source: {source}")
        lines.append(
            f"-- 注：{len(extension['sources'])} 处迁移各写一次同一条幂等语句，此处只保留一条"
        )
        lines.append(_terminate(extension["sql"]))
    if not snapshot["extensions"]:
        lines.append("-- （无）")
    lines.append("")

    lines.append("-- ===== 2. 表与所属索引（源①：ORM metadata 编译，按表名排序）=====")
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        ddl = str(CreateTable(table, include_foreign_key_constraints=[]).compile(dialect=PG_DIALECT))
        lines.append(_terminate(ddl))
        for index in sorted(table.indexes, key=_index_sort_key):
            lines.append(_terminate(str(CreateIndex(index).compile(dialect=PG_DIALECT))))
    lines.append("")

    lines.append(
        f"-- ===== 3. 外键约束（源①，{counts['foreign_keys']} 条；ALTER 形式便于按表名排序后仍可执行）====="
    )
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        for constraint in sorted(table.foreign_key_constraints, key=_foreign_key_sort_key):
            lines.append(_terminate(_alter_add_foreign_key(table.name, constraint, PG_DIALECT)))
    lines.append("")

    lines.append(
        f"-- ===== 4. 迁移 raw DDL 索引（源②，{counts['raw_indexes']} 个；ORM 无法表达）====="
    )
    lines.append("-- 🔴 这一段是「纯 ORM 编译路线会静默漏掉」的部分：删掉任何一个即 RAG 检索能力失真")
    for raw_index in snapshot["raw_indexes"]:
        lines.append(f"-- source: {raw_index['source']}")
        lines.append(_terminate(raw_index["sql"]))
    lines.append("")
    return "\n".join(lines) + "\n"


def render_sqlite_sql(metadata: MetaData, snapshot: dict[str, Any]) -> str:
    """渲染 SQLite 侧完整 DDL（表 + 索引 + FTS5 虚表/影子表/触发器）。

    Args:
        metadata: ORM metadata。
        snapshot: :func:`build_sqlite_snapshot` 的产物。

    Returns:
        以 ``\\n`` 结尾的 SQL 文本。
    """
    counts = snapshot["counts"]
    lines = _header_lines(
        "WBTimeAI DDL 冻结面 · SQLite（schema v0018）",
        snapshot,
        [
            (
                "🔴 hnsw 系 PG 专属（pgvector USING hnsw），SQLite 侧**不存在**——"
                "合法的 dialect_only: pg 差异，不是遗漏；"
                "PG 侧对应对象见 schema.v0018.pg.sql 第 4 段"
            ),
            "段落顺序：1) 表 + 所属索引（按表名排序）→ 2) FTS5 虚表 → 3) 影子表 → 4) 同步触发器",
            "影子表定义取自 sqlite_master（SQLite 内部生成，源文件无 DDL），故为权威文本",
        ],
    )

    lines.append("-- ===== 1. 表与所属索引（源①：ORM metadata 编译，按表名排序）=====")
    for table in sorted(metadata.tables.values(), key=lambda item: item.name):
        ddl = str(
            CreateTable(
                table,
                include_foreign_key_constraints=list(table.foreign_key_constraints),
            ).compile(dialect=SQLITE_DIALECT)
        )
        lines.append(_terminate(ddl))
        for index in sorted(table.indexes, key=_index_sort_key):
            lines.append(_terminate(str(CreateIndex(index).compile(dialect=SQLITE_DIALECT))))
    lines.append("")

    groups: list[tuple[str, str, bool]] = [
        ("2. FTS5 虚表（源③：迁移 0013 _create_sqlite_fts，raw DDL）", "virtual_table", True),
        ("3. FTS5 影子表（源③：SQLite 内部生成，sqlite_master 回读）", "shadow_table", False),
        ("4. FTS5 同步触发器（源③：ai / ad / au）", "trigger", True),
    ]
    for title, kind, replayable in groups:
        lines.append(f"-- ===== {title} =====")
        if not replayable:
            lines.append(
                "-- 🔴 影子表由 CREATE VIRTUAL TABLE **隐式创建**，SQLite 里再显式建会直接报"
                " `table ... already exists`。"
            )
            lines.append(
                "--    因此下列语句以注释形式冻结（权威文本取自 sqlite_master），"
                "执行本文件时它们会由虚表自动生成。"
            )
        if kind == "trigger":
            lines.append(
                "-- 🔴 功能性对象：external content 模式下缺这三个触发器，FTS 索引不随基表"
                " INSERT/UPDATE/DELETE 更新，关键词检索静默返回旧结果"
            )
            lines.append("--    原文取自 sqlite_master（与迁移 0013 _create_sqlite_fts 逐字一致）")
        selected = [item for item in snapshot["dialect_only"] if item["kind"] == kind]
        if not selected:
            lines.append("-- （无）")
        for item in selected:
            lines.append(f"-- source: {item['source']}")
            rendered = _terminate(item["sql"])
            lines.append(rendered if replayable else f"-- [sqlite_master] {rendered}")
        lines.append("")
    by_kind = counts.get("dialect_only_by_kind", {})
    lines.append(
        f"-- 汇总：方言专属对象 {counts['dialect_only_objects']} 个"
        f"（虚表 {by_kind.get('virtual_table', 0)} + 影子表 {by_kind.get('shadow_table', 0)}"
        f" + 触发器 {by_kind.get('trigger', 0)}；PG DDL 里 0 处）"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def dump_json(payload: dict[str, Any]) -> str:
    """稳定序列化 normalized 快照（固定缩进 / 保留键序 / UTF-8 原样 / 结尾换行）。"""
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
