# DDL 冻结面抽取（C-03）· 三源合并说明

> 产出对象：`contracts/schema.v0018.{pg,sqlite}.{sql,normalized.json}` + `contracts/db/type-map.csv`
> 契约版本：`schema_version = v0018`（迁移链 0018 收敛态）· 冻结版本：`V0.0.1`

---

## 0. 一句话

**DDL 冻结面不得由单一编译命令产出。** 纯 `Base.metadata` 编译会**静默漏掉 2 个 hnsw 向量索引**
（metadata 编译结果里 `hnsw` 出现 0 次），只取 PG 会**静默漏掉 SQLite 的 FTS5 全文检索对象**
（PG DDL 里出现 0 处）。两类漏项都不会报错、不会让任何测试变红——所以必须**三源合并 + 逐对象对账**。

| 源 | 取法 | 内容（实测） | 为什么必须单列 |
|---|---|---|---|
| ① ORM metadata 编译 | `Base.metadata` → PG / SQLite 方言编译 | **61 表 / 629 列 / 174 索引**（`unique` 7 / `partial` 1） | 常规对象的唯一来源 |
| ② 迁移链 raw DDL | AST 解析 `migrations/versions/*.py` 的 `op.execute(...)` | **2 个 hnsw** + 2 条 `CREATE EXTENSION` 语句 | `Base.metadata` **表达不了**；纯 ORM 路线静默漏 |
| ③ SQLite 方言专属 | 内存 SQLite 真建 FTS5 后回读 `sqlite_master` | **8 个对象**（1 虚表 + 4 影子表 + 3 触发器） | PG DDL 里 **0 处**；只取 PG 会丢掉社区默认档的关键词检索 |

**合并后索引对象 = 174 + 2 = 176**（`unique` 7 / `partial` 1 均在 metadata 174 之内）。

---

## 1. 复现命令（一切数字都必须能重跑出来）

```bash
# 位置：新仓根 D:/WBT/WBTimeAI
# 解释器：脚本会自己切到旧仓 .venv（Python 3.12.10），无需手动设 PYTHONPATH
python scripts/extract-from-py/ddl/export_ddl.py          # 生成 4 个文件
python scripts/extract-from-py/ddl/gen_type_map.py        # 生成 type-map.csv

# 只校验、不落盘（漂移则退出码 1）
python scripts/extract-from-py/ddl/export_ddl.py --check
python scripts/extract-from-py/ddl/gen_type_map.py --check
```

可选参数：`--source D:/WBT/WBTimeAI_old`（等价于 `$WBTIME_SOURCE`）、`--out-dir`、`--quiet`。

> 解释器无关：用系统 Python（实测 3.13.14）直接跑也可以——脚本在 import SQLAlchemy **之前**
> 完成守卫，发现当前解释器没有 SQLAlchemy 就自动用旧仓 `.venv`（3.12.10）重执行一次
> （哨兵 `$WBTIME_DDL_REEXEC` 防递归）。**两种解释器跑出的四个 sha256 完全相同**，
> 即产物与解释器版本无关。

### 1.1 底层事实的独立复核命令（不经本目录脚本，用于交叉验证）

```bash
cd /d/WBT/WBTimeAI_old
W=$(pwd -W)
PP=$(for d in packages/*/src; do printf "%s;" "$W/$d"; done)$W/apps/api/src\;$W/apps/cli/src\;$W/apps/worker/src
PYTHONPATH="$PP" ./.venv/Scripts/python.exe -c "
from sqlalchemy.dialects import postgresql
from wbtime_ai_database.base import Base
import wbtime_ai_database.models
md = Base.metadata
idx = [i for t in md.tables.values() for i in t.indexes]
print('tables', len(md.tables), 'columns', sum(len(t.columns) for t in md.tables.values()))
print('indexes', len(idx), 'unique', sum(1 for i in idx if i.unique))
"
```

实测输出：

```
tables 61 columns 629
indexes 174 unique 7
```

hnsw 不在 metadata 里（这就是源② 存在的理由）：

```bash
PYTHONPATH="$PP" ./.venv/Scripts/python.exe -c "
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from wbtime_ai_database.base import Base
import wbtime_ai_database.models
pg = postgresql.dialect(); md = Base.metadata
text = ''.join(str(CreateTable(t).compile(dialect=pg)) for t in md.tables.values())
text += ''.join(str(CreateIndex(i).compile(dialect=pg)) for t in md.tables.values() for i in t.indexes)
print('hnsw occurrences in metadata-compiled PG DDL =', text.lower().count('hnsw'))
print('VECTOR(1536) occurrences =', text.count('VECTOR(1536)'))
"
```

```
hnsw occurrences in metadata-compiled PG DDL = 0
VECTOR(1536) occurrences = 2
```

对照迁移文件里的 hnsw 语句：

```bash
cd /d/WBT/WBTimeAI_old && grep -rn "USING hnsw" migrations/versions/
```

```
migrations/versions/0013_phase2_knowledge.py:295:            "USING hnsw (vector vector_cosine_ops) "
migrations/versions/0014_phase2_memory.py:197:            "USING hnsw (vector vector_cosine_ops) "
```

> 📌 行号说明：文档记载 295 / 197 是**字符串字面量**所在行；本工具用 AST 记录的是
> **`op.execute(...)` 调用**所在行（**293 / 195**）。两者指同一语句，差异已登记（见 §8 D-3）。

---

## 2. 源②：迁移链 raw DDL（2 个 hnsw）

### 2.1 取法（为什么不执行迁移，而做 AST 静态求值）

迁移里的 DDL 是 `op.execute(f"CREATE INDEX {_HNSW_INDEX_NAME} ON embedding " "USING hnsw ...")`
这样的**编译期可求值**表达式。本工具用 `ast` 只求值字符串形状（`Constant` / `JoinedStr` /
`BinOp(+)`），`FormattedValue` 从模块级 `_HNSW_INDEX_NAME = "..."` 常量表里取——**不执行模块**，
因此不触发任何副作用（不连库、不改文件、不依赖 `op` 上下文）。形状不可静态求值时**跳过并保持沉默**
是危险的，所以 `export_ddl.py` 对「必须出现的 2 个索引名」做**硬断言**：缺一个直接退出码 2。

### 2.2 提取结果（原文，未改写）

| 索引名 | 表 | 方法 | 算子类 | 参数 | 迁移位置（AST 行号） |
|---|---|---|---|---|---|
| `ix_embedding_vector_hnsw` | `embedding` | `hnsw` | `vector_cosine_ops` | `m = 16, ef_construction = 64` | `0013_phase2_knowledge.py:293`（字面量 295 行） |
| `ix_memory_vector_hnsw` | `memory` | `hnsw` | `vector_cosine_ops` | `m = 16, ef_construction = 64` | `0014_phase2_memory.py:195`（字面量 197 行） |

```sql
CREATE INDEX ix_embedding_vector_hnsw ON embedding USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX ix_memory_vector_hnsw ON memory USING hnsw (vector vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

前置依赖也一并冻结（源②，2 处迁移各写一次、语句幂等，故去重后 1 条、保留两条溯源）：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- source: 0013_phase2_knowledge.py:104 / 0014_phase2_memory.py:95
```

`migrations/env.py:41` 的 `_HNSW_DB_ONLY_INDEXES` 白名单只是「autogenerate 时忽略」的声明，
**不是** DDL 来源——冻结面取的是迁移里真正会执行的语句。两者必须一致，本工具的断言正好守住这一点。

---

## 3. 源③：SQLite 方言专属（8 个对象）

### 3.1 取法

影子表（`_data` / `_idx` / `_docsize` / `_config`）**在任何源文件里都没有 DDL**——它们由 SQLite
内部生成。唯一可信的取法是：把迁移里的 `CREATE VIRTUAL TABLE` + 3 条 `CREATE TRIGGER` 在
**内存 SQLite** 里真建一遍，再 `SELECT * FROM sqlite_master` 回读。因此本目录取到的是
**SQLite 自己写下的权威文本**，不是人抄的。

external-content 模式（`content='document_chunk'`）在建虚表时会校验内容表存在，所以工具先建一张
**占位内容表**（列取自触发器里 `new./old.` 引用的列），建完即丢弃——不影响影子表结构。

### 3.2 提取结果

| # | 对象名 | 类型 | 归属 | 来源 |
|---|---|---|---|---|
| 1 | `document_chunk_fts` | FTS5 **虚表** | — | `0013_phase2_knowledge.py:141`（`_create_sqlite_fts`） |
| 2 | `document_chunk_fts_config` | **影子表** | `document_chunk_fts` | `sqlite_master` 回读 |
| 3 | `document_chunk_fts_data` | **影子表** | `document_chunk_fts` | `sqlite_master` 回读 |
| 4 | `document_chunk_fts_docsize` | **影子表** | `document_chunk_fts` | `sqlite_master` 回读 |
| 5 | `document_chunk_fts_idx` | **影子表** | `document_chunk_fts` | `sqlite_master` 回读 |
| 6 | `document_chunk_ai` | **触发器**（AFTER INSERT） | `document_chunk` | `0013_phase2_knowledge.py:145` |
| 7 | `document_chunk_ad` | **触发器**（AFTER DELETE） | `document_chunk` | `0013_phase2_knowledge.py:149` |
| 8 | `document_chunk_au` | **触发器**（AFTER UPDATE） | `document_chunk` | `0013_phase2_knowledge.py:154` |

```sql
CREATE VIRTUAL TABLE document_chunk_fts USING fts5(content, content='document_chunk', content_rowid='rowid');
CREATE TABLE 'document_chunk_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE TABLE 'document_chunk_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE 'document_chunk_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE 'document_chunk_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
-- 3 个同步触发器（原文取自 sqlite_master，与迁移 0013 逐字一致）
CREATE TRIGGER document_chunk_ai AFTER INSERT ON document_chunk BEGIN INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END;
CREATE TRIGGER document_chunk_ad AFTER DELETE ON document_chunk BEGIN INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); END;
CREATE TRIGGER document_chunk_au AFTER UPDATE ON document_chunk BEGIN INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content); END;
```

> 🔴 **`_content` 影子表不存在**。external-content 模式下内容就在 `document_chunk` 里，FTS5 不建
> `_content`。文档「虚表 + 5 张影子表 = 6 对象」的口径因此是**6 ≠ 实测 8**，见 §8 D-1 / §8.1。

### 3.2.1 触发器为什么是**功能性对象**（不是装饰对象）

external-content 模式下，FTS5 **只存索引、不存原文**，索引的唯一更新途径就是这 3 个触发器。
缺了它们，**索引永远停在空表状态**，`MATCH` 恒返回 0 行——而且是**静默**的（不报错、不告警）。

实测（把冻结的 `schema.v0018.sqlite.sql` 建到内存库，插一行 `content='hello world'` 再查）：

```
— WITH 3 triggers (frozen snapshot) —
  MATCH 'hello' → 1
  after UPDATE: MATCH 'goodbye' → 1 | MATCH 'hello' → 0     ← 索引跟随基表更新，正确
— WITHOUT triggers (simulating the gap) —
  MATCH 'hello' → 0   ← 连初次写入都没进索引
  after UPDATE: MATCH 'goodbye' → 0   ← 检索静默失真
```

因此「SQLite 侧只需虚表 + 影子表」是**错的**；触发器必须一起冻结，且必须可执行（不是注释）。

### 3.3 影子表在 `.sql` 里为什么是注释

`CREATE VIRTUAL TABLE` 会**隐式**建出 4 张影子表；再显式 `CREATE TABLE` 同一名字会直接报
`table 'document_chunk_fts_config' already exists`（本工具第一次跑就是这么炸的）。因此：

* `schema.v0018.sqlite.sql` 第 2 段（虚表）、第 4 段（触发器）**可执行**；
* 第 3 段（影子表）以 `-- [sqlite_master] ...` **注释形式冻结**权威文本，并在段首说明原因。

结果：整份 SQLite 文件**仍可直接整段执行**（`executescript`），执行后影子表由 FTS5 自动生成，
对象集与真跑迁移链**完全一致**（§5 有对比输出）。

---

## 4. `schema.v0018.*` 四个产物

| 文件 | 内容 | 结构要点 |
|---|---|---|
| `schema.v0018.pg.sql` | ① 扩展 → ② 61 表 + 所属索引（**按表名排序**）→ ③ 159 条 `ALTER TABLE ADD ... FOREIGN KEY` → ④ 2 个 hnsw | 外键**延后**为 `ALTER`，让「按表名排序」与「整份文件可执行」同时成立 |
| `schema.v0018.pg.normalized.json` | 同上的结构化快照 | `{dialect, schema_version, frozen_contract, generated_by, counts, tables[], raw_indexes[], extensions[], triggers[], dialect_only[], notes[]}` |
| `schema.v0018.sqlite.sql` | ① 61 表 + 所属索引 → ② FTS5 虚表 → ③ 影子表（注释冻结）→ ④ 3 触发器（**可执行**） | 头注释显式登记「hnsw 系 PG 专属，SQLite 侧不存在」+ 源③ 分解式 `虚表 ×1 + 影子表 ×4 + 触发器 ×3` |
| `schema.v0018.sqlite.normalized.json` | 同上 | **与 PG 快照顶层键完全同构**，可直接 diff |

`tables[]` 单表结构（两份快照一致）：

```json
{
  "name": "document_chunk",
  "columns": [{"name": "id", "type": "UUID", "nullable": false, "default": null}],
  "primary_key": ["id"],
  "unique_constraints": [{"name": "uq_document_chunk_document_ordinal", "columns": ["document_id", "ordinal"]}],
  "foreign_keys": [{"name": null, "columns": ["document_id"], "referred_table": "document", "referred_columns": ["id"], "ondelete": null, "onupdate": null}],
  "indexes": [{"name": "ix_document_chunk_document_id", "columns": ["document_id"], "unique": false, "where": null}]
}
```

`triggers[]`（SQLite 快照 3 条；PG 快照为 `[]`，保持顶层键同构）：

```json
{
  "name": "document_chunk_au",
  "table": "document_chunk",
  "timing": "AFTER",
  "event": "UPDATE",
  "body": "INSERT INTO document_chunk_fts(document_chunk_fts, rowid, content) VALUES ('delete', old.rowid, old.content); INSERT INTO document_chunk_fts(rowid, content) VALUES (new.rowid, new.content);",
  "body_sha256": "dd8a2f97430766d5d43035b031a497d453ff9266bb7a4548c919f75ccefbc48b",
  "sql": "CREATE TRIGGER document_chunk_au AFTER UPDATE ON document_chunk BEGIN ... END;",
  "source": "sqlite_master（执行 0013 FTS5 语句后回读）"
}
```

`counts` 里另有 `dialect_only_by_kind`（PG `{index: 2}` / SQLite `{shadow_table: 4, trigger: 3, virtual_table: 1}`）
与 `triggers` / `virtual_tables` / `shadow_tables` 三个标量，供台账直接引用，不必再数数组长度。

**稳定性保证**（文件可逐字节 diff）：
表按名称升序 · 列按 DDL 定义序 · 索引按名称序 · 约束按 (名称, 列) 全序（无名约束用列名兜底，
否则 `set` 迭代序会随 `PYTHONHASHSEED` 漂移——这是本工具踩过并修掉的真实 bug）·
`json.dumps(ensure_ascii=False, indent=2)` + 结尾换行 · 换行一律 `\n`。

---

## 5. 校验：SQLite 侧 snapshot 可重放，且与真跑迁移链逐对象相等

```bash
# 1) 真跑一遍迁移链，落到临时库（不在 _old 里写任何东西）
cd /d/WBT/WBTimeAI_old && W=$(pwd -W) && PP=$(for d in packages/*/src; do printf "%s;" "$W/$d"; done)$W/apps/api/src\;$W/apps/cli/src\;$W/apps/worker/src
PYTHONPATH="$PP" WBTIME_AI_DATABASE_URL="sqlite:///D:/tmp_c03_probe.db" \
  ./.venv/Scripts/python.exe -m alembic -c alembic.ini upgrade head

# 2) 把 snapshot 执行到内存库，两边 sqlite_master 对比
cd /d/WBT/WBTimeAI && python - <<'PY'
import sqlite3, pathlib
c = sqlite3.connect(":memory:")
c.executescript(pathlib.Path("contracts/schema.v0018.sqlite.sql").read_text(encoding="utf-8"))
real = sqlite3.connect("D:/tmp_c03_probe.db")
q = lambda conn, t: sorted(r[0] for r in conn.execute(
    "select name from sqlite_master where type=?", (t,)))
for kind in ("table", "trigger"):
    a, b = q(c, kind), q(real, kind)
    print(kind, len(a), len(b), a == b)
for label, pred in (("named index", lambda n: not n.startswith("sqlite_autoindex")),
                    ("autoindex", lambda n: n.startswith("sqlite_autoindex"))):
    a = {n for n in q(c, "index") if pred(n)}
    b = {n for n in q(real, "index") if pred(n)}
    print(label, len(a), len(b), a == b)
PY
```

实测输出：

```
table    snapshot= 66 migrated= 67 equal=False        ← 唯一差异：alembic_version（迁移台账表，非 schema 对象）
   diff: ['alembic_version']
trigger  snapshot=  3 migrated=  3 equal=True
named index  snapshot=174 migrated=174 equal=True
autoindex    snapshot= 90 migrated= 91 equal=False    ← 唯一差异：sqlite_autoindex_alembic_version_1
   diff: ['sqlite_autoindex_alembic_version_1']
```

结论：**66 = 61 业务表 + 1 FTS5 虚表 + 4 影子表**；174 命名索引与 3 触发器**逐名相等**。
真库 `sqlite_master` 索引总数 265 ≠ 174，是因为 SQLite 会给「非 INTEGER 主键」（61 个）
与「表级 UNIQUE 约束」（29 个）自动建 `sqlite_autoindex_*`：`61 + 29 = 90`，
再 `265 = 174 命名 + 90 自动 + 1（alembic_version）`。这部分**隐式对象不入冻结计数**，
是口径问题不是漏项。

> PG 侧无本地实例，未做「重放后对比 `pg_indexes`」这一步（路线图 §3.3 把 PG parity 降级到
> V0.1.0 前置，需要隧道或 `information_schema` 导出）。**当前为未验证缺口，见 §9.1 / §8 D-6。**

---

## 6. `type-map.csv`：以 **PG 方言 emit 类型**为准（M-01，P0）

### 6.1 为什么不能用 `str(col.type)`

`GUID` / `JSONType` / `VectorType` 都是 `TypeDecorator`，`str(col.type)` 渲染的是 **impl**，
不是方言 emit 类型——这**正是**路线图 M-01 说的 411 列错算的来源：

| 声明（`repr(col.type)`） | `str(col.type)`（impl，会骗人） | **PG emit** | SQLite emit |
|---|---|---|---|
| `GUID(length=36)` | `CHAR(36)` | **`UUID`** | `CHAR(36)` |
| `DateTime(timezone=True)` | `DATETIME` | **`TIMESTAMP WITH TIME ZONE`** | `DATETIME` |
| `JSONType()` | `JSON` | **`JSONB`** | `JSON` |
| `VectorType()` | `JSON` | **`VECTOR(1536)`** | `JSON`（降级） |

两个真坑：`uuid` vs `char(36)` 在 PG 上**外键类型不兼容**（不是风格差异）；
`timestamptz` 建成无时区 `timestamp` 会让**时间比较静默偏移**（117/117 全带时区，不是 0 带）。

CSV 里 `declared_type` 与 `declared_str_type` **并排保留**，把上面这张对照表变成可机读证据。

### 6.2 实测计数

| 口径 | 实测 | 说明 |
|---|---|---|
| 逐列映射行数 | **629** | 与 metadata 列总数一致，一列不落 |
| 口径A：**PG emit ≠ SQLite emit** 的方言敏感列 | **401** | `UUID` 224 / `TIMESTAMP WITH TIME ZONE` 117 / `JSONB` 58 / `VECTOR(1536)` 2 |
| 口径B：声明敏感族（`GUID`/`DateTime`/`JSONType`/`VectorType`） | **403** | `224 + 117 + 60 + 2`（60 = `JSONType` 58 + 纯 `JSON` 2） |
| 口径A 与口径B 的差 | **2** | 差集恰为 `plugin.permissions` / `plugin.manifest`（声明 `JSON`，两侧 emit 都是 `JSON`，**不敏感**） |
| `str(type)` ≠ PG emit 的列（M-01 陷阱面） | **401** | 与口径A 同一批 |
| 声明 JSON 族 | **62** | `JSONType()` 58 + 纯 `JSON()` 2 + `VectorType()` 2 |
| 未命中映射策略的列 | **0** | 判据：逐列有映射记录，任何 `unmapped` 都退出码 1 |

> 🔴 **裁定（team-lead 2026-10-20）：文档的 `405` 作废，标为「文档口径错误（重复计数）」。**
>
> 文档算式是 `224 + 117 + 62 + 2 = 405`。问题在末项：**62 这个「声明 JSON 族」里已经含了
> 那 2 个 `VectorType` 列**（`VectorType.impl = JSON`），再 `+ 2` 就是把同一批列算了两遍。
> 干净地拆开只有两个可复算口径：
>
> | 口径 | 算式 | 值 |
> |---|---|---|
> | A：PG emit 与 SQLite emit 不同 | `224 + 117 + 58 + 2` | **401** |
> | B：声明类型属方言敏感族 | `224 + 117 + (58 + 2) + 2` | **403** |
> | 文档的 405 | `224 + 117 + (58 + 2 + 2) + 2` ← 后两个 `+2` 是同一批 `VectorType` | ~~405~~ **作废** |
>
> 产物只写 **401**（`counts` / 台账 / 报告统一用这个），`gen_type_map.py` 输出里并列展示 401 与 403
> 供对账；**不为对齐文档而制造 405**。这是 M-01 修正本身没修干净的地方（原意是「必须写明是哪个
> 口径」，却留了个算错的第二值）。

### 6.3 策略表（唯一需要人写的部分）

| 声明类型 | `ts_target` | `strategy` | 理由 |
|---|---|---|---|
| `GUID` | `string` | `uuid-string` | PG `uuid` / SQLite `CHAR(36)`，统一按字符串读写（`as_uuid=False`） |
| `DateTime` | `string` | `timestamptz-iso8601` | 必须带时区偏移输出，禁止裸本地时间 |
| `JSONType` | `unknown` | `jsonb-opaque` | 契约层不解构内部结构（stringly-contract） |
| `VectorType` | `number[]` | `vector-1536-number-array` | 维度 1536 写死在列类型里；SQLite 侧为 JSON 降级 |
| `Boolean` | `boolean` | `bool-passthrough` | 两侧 emit 相同 |
| `Integer` | `number` | `int32-number` | 两侧 emit 相同 |
| `Float` | `number` | `double-number` | 两侧 emit 相同 |
| `Numeric(18,6)` | `string` | `decimal-string` | 定点小数按字符串传，避免 IEEE754 精度丢失 |
| `Text` | `string` | `text-passthrough` | — |
| `String(n)` | `string` | `varchar-passthrough` | 长度约束留在 DB 侧，TS 不重复编码 |

兜底：声明类名未登记时按 PG emit 类型判（`_FALLBACK_BY_PG_TYPE`），最终仍有 `unmapped` 就退出码 1。

---

## 7. 双侧差异对账（每条差异都必须能解释）

| 差异 | PG 侧 | SQLite 侧 | 归类 |
|---|---|---|---|
| hnsw 向量索引 | `ix_embedding_vector_hnsw` / `ix_memory_vector_hnsw` | **不存在** | `dialect_only: pg`（pgvector 专属索引类型） |
| FTS5 虚表 + 影子表 + 触发器 | **不存在** | 8 个对象（§3.2） | `dialect_only: sqlite` |
| `uuid` 列 | `UUID` | `CHAR(36)` | 类型差异，`type-map.csv` 逐列登记 |
| 时间列 | `TIMESTAMP WITH TIME ZONE` | `DATETIME` | 同上 |
| JSON 列 | `JSONB` 58 / `JSON` 2 | `JSON` 62 | 同上 |
| 向量列 | `VECTOR(1536)` 2 | `JSON` 2 | 同上 + 与 hnsw 同族 |
| 部分索引 WHERE | `checkout_ref IS NOT NULL` | 同（`sqlite_where` 同步声明） | 无差异（模型两侧都写了） |

**交集为空**（`[]`）——两类专属对象互不相交，这正是「双侧都不能省」的机器证据。

---

## 8. 与文档记载的差异（以实测为准，禁止改数字凑文档）

| # | 文档说法 | 实测 | 处理 |
|---|---|---|---|
| **D-1** | 「`document_chunk_fts` 虚表 + **5 张影子表**」= 6 对象（`migrations/env.py:42`） | **虚表 ×1 + 影子表 ×4**（无 `_content`）+ **触发器 ×3** = **8 对象** | ①文档称 5 张影子表，**实测 4 张**：external-content 模式不建 `_content`，差额 1 已核实为**设计事实而非遗漏**，拒绝为凑「5」臆造 `_content`；②文档**完全未登记**那 3 个触发器（只说了虚表和影子表），实测补入并标为「文档未登记项」，见 §8.1 |
| **D-2** | 方言敏感列 **401 / 405** 两口径 | **401**（emit 差异）/ **403**（声明族） | **裁定：405 作废 = 文档口径错误（重复计数）**，算式见 §6.2。产物只写 401，`gen_type_map.py` 并列打印 401/403 供对账；不为对齐文档制造 405 |
| **D-3** | hnsw 在 `0013:295` / `0014:197` | AST 记录 `0013:293` / `0014:195` | 文档指的是**字符串字面量**行，工具记录的是 **`op.execute` 调用**行，同一语句，不修改任何一侧 |
| **D-4** | 索引总数「176 = 174 + 2」 | **一致** | 无差异；另补充 `unique` 7 / `partial` 1 均在 174 之内，`unique_constraints` 29 是**另一个集合**，不得混算 |
| **D-5** | —（文档未提） | **155 / 159 外键无名字** | 不臆造名字，`ALTER TABLE ... ADD FOREIGN KEY`（无名）如实渲染，`normalized.json` 记 `name: null`。**裁定：不补名**（补名会改 normalized hash = 范围变更）。风险与 V0.1.0 判据修正见 §9.2 |
| **D-6** | —（文档未提） | **PG 侧已做结构自检**（61 `CREATE TABLE` / 176 `CREATE INDEX` / 159 `ALTER` / 1 `CREATE EXTENSION`）；**真实例重放未做** | **计划内边界**：路线图 §3.3 把 ①PG 隧道 / ⑤`pg_dump` 明确降为 V0.1.0 parity 前置。**当前为未验证缺口**，禁止表述为「PG 侧已验证」。见 §9.1 |

### 8.1 文档**未登记**的对象（实测补入，供台账回写）

路线图 §3.3.1 的源③ 只写了「`document_chunk_fts` 虚表 + 5 张影子表」，**没有提触发器**。
实测该类对象共 **8** 个，其中 3 个属文档未登记：

| 对象 | 类型 | 为什么必须补登 |
|---|---|---|
| `document_chunk_ai` | 触发器 AFTER INSERT | 缺它 → 新插入的分块**永不进索引**（实测 `MATCH` 返回 0） |
| `document_chunk_ad` | 触发器 AFTER DELETE | 缺它 → 删除后索引残留，**已删内容仍可被检索到** |
| `document_chunk_au` | 触发器 AFTER UPDATE | 缺它 → 改内容后**搜旧词命中、搜新词不命中** |

三条都是 external-content FTS5 的**唯一**索引同步路径，属功能性对象（证据见 §3.2.1）。
§3.3.1 的口径建议回写为：`FTS5 虚表 ×1 + 影子表 ×4 + 同步触发器 ×3 = 8 个对象`。

---

## 9. 风险与未确认项

### 9.1 PG 侧：结构自检通过，真实例重放**未做**（D-6，计划内边界）

`schema.v0018.pg.sql` 目前只做了**结构性自检**：61 `CREATE TABLE` / 176 `CREATE INDEX`
（169 普通 + 7 `UNIQUE`，含 2 个 hnsw）/ 159 `ALTER TABLE ... ADD FOREIGN KEY` / 1 `CREATE EXTENSION`。

**没有在真 PG 实例上跑过**（本机 `psql` NONE）。这不是本版缺陷，而是路线图 §3.3 划定的边界：
①PG 隧道 / ⑤`pg_dump` 明确降为 **V0.1.0 的 parity 前置**，V0.0.1 只要求
③`pgvector` 可装 / ④DDL 重编译出 `VECTOR(1536)` / ⓔ`PYTHONPATH` 三项（三项全绿）。

🔴 **表述纪律**：只能写「PG 侧已做结构自检；真实例重放归 V0.1.0 前置，**当前为未验证缺口**」。
**不得**写「PG 侧已验证」——`hnsw` 语句还额外依赖 `pgvector` 扩展在位，未经真实例执行即无证据。

### 9.2 155 条无名外键（D-5）：不补名 + V0.1.0 判据修正

实测 **155 / 159** 外键没有名字（只有 `fk_agent_current_version_id` 等 4 个在模型里显式命名）。

- **处置**：**不补名**。渲染为无名 `ALTER TABLE ... ADD FOREIGN KEY`，JSON 记 `name: null`。
  补名会改变 DDL 的 normalized hash ⇒ 属**范围变更**（`施工纪律.md` §4.5.2），V0.0.1 无权自行做。
- **风险写死**：PG 会按 `<表>_<列>_fkey` **自动命名**。一旦重放顺序、重建次数或 PG 版本变化导致
  自动命名规则/冲突消解方式改变，约束名就会漂移 —— 此时「按名字比对」的 parity 检查会**误报**。
- **V0.1.0 判据修正（必须）**：parity 比对按 **`(表, 列集合, 引用目标)` 逻辑等价**判定，
  **不得**用「约束名字相等」。若届时坚持按名字比对，须先回路线图 §2 走「补名」的范围裁定。

### 9.3 其他

1. **`_old` 只读**：全程未写入 `_old`。验证用的临时库曾落在 `D:/tmp_c03_probe.db`，
   **已删除**（§5 有重生成命令，`--check` 不依赖它）。临时物不属契约产物。
2. **`FTS5` 依赖运行期 SQLite 编译选项**：影子表结构由 SQLite 版本决定（本次为 Python 3.12.10
   ／其内置 SQLite）。跨 SQLite 版本重抽若影子表 DDL 变化，属**真实差异**，须走范围变更而不是静默接受。
3. **C-01 基座耦合（已收口，单一实现）**：本目录 `_env.py` 现在**全部委托** C-01 基座
   `scripts/extract-from-py/_bootstrap.py`（`make_context` / `install_import_paths` /
   `run_python` / `child_env`），C-03 并行期内置的那份「等价回退实现」**已删除**
   （路径规范化 / `*/src` 枚举 / 解释器定位 / 子进程环境，一行都不再复制）。
   基座缺失时直接抛 `EnvError` 并给出修复路径，**不再**悄悄走另一套逻辑——
   因为两份实现迟早分叉，而路径规范化错了的表现是 `ModuleNotFoundError`，极难定位。
   代价：本目录不再是「基座缺失也能跑」的独立包，但这正是 C-01 收口后的预期依赖方向。
4. **`run.py` 集成与台账纪律**：`ddl/exporter.py` 已注册（`python scripts/extract-from-py/run.py export`
   会连带重生成 DDL 四件套 + `type-map.csv`）。⚠️ **产物一旦变化，必须走完整 `run.py export`**：
   它同时重建两本台账（`manifest.sha256` + `contract-manifest.json`）并自校验。
   **不要**只调 `hashes.write_manifest()`——那只刷文件级 sha256，`contract-manifest.json`
   会变成过期状态，`check` 报 `object ledger digest != disk`（2026-10-20 由 C-07 实测确认）。
   仅当产物**逐字节未变**（如纯代码重构后 `--check` 全绿）才可跳过重建。

5. **冻结窗口内的写盘顺序（QA 基准依赖产物的字节，不依赖"脚本能跑"）**：
   `--check` 是**只读**，`ddl.exporter.export(ctx)` 与 `run.py export` 都是**会写产物**的路径。
   正确顺序是 ①先 `--check` 确认零漂移 → ②**再**决定是否需要写 → ③确实要写就走完整
   `run.py export`（一次更新两本台账），**不要**单独特调 exporter。
   反例（机制上很危险）：重构后字节漂了却只跑了 `--check`（它只会报 FAIL 而不会修复），
   或只跑了 exporter（产物新了、台账旧了）——两种情况下 QA 手里的 sha 基准都会静默作废。
   2026-10-20 `_env` 收敛即按此顺序执行：`--check` 全绿 → 才调 `export(ctx)` → 五个 sha 未变 →
   `run.py check` exit 0，故台账无需重建。

---

## 10. 已修 bug 与确定性凭证

确定性是「可 diff / 可对账」的前提，所以这三个 bug 的**复跑凭证**保留在这里，不是过程噪声。

### 10.1 `PYTHONHASHSEED` 导致 normalized 快照漂移（最严重的一个）

**症状**：`--check` 偶发报 `内容漂移（sha256 不一致）`，但源码与依赖都没改。
**根因**：155 条外键 + 部分 UNIQUE 约束 `name is None`，排序键退化成空串 `""`，
并列项的先后顺序由 `set` 的迭代序决定 ⇒ 随进程 hash 随机化漂移 ⇒ JSON 字节序变。
**修法**：所有排序键改成**全序**：`(名称 or "", 列名元组[, 引用目标])`；约束/索引/表/列一律显式 key。
**凭证**（两个 seed 独立进程，输出 5 个文件 sha256 完全一致，且与入库产物一致）：

```
$ for seed in 1 12345; do PYTHONHASHSEED=$seed python scripts/extract-from-py/ddl/export_ddl.py \
      --out-dir /tmp/ddl_seed_$seed --quiet; done
                                           seed=1                             seed=12345
schema.v0018.pg.sql                        7cb4c0535618b4550c9723350bea7bf8  7cb4c0535618b4550c9723350bea7bf8
schema.v0018.pg.normalized.json            d9cc2746cd5487f89e6a608b3f299915   d9cc2746cd5487f89e6a608b3f299915
schema.v0018.sqlite.sql                    65ee733d230e224e824e68691f0f20c62  65ee733d230e224e824e68691f0f20c62
schema.v0018.sqlite.normalized.json        7218eafc80f667381474816046372f80f4  7218eafc80f667381474816046372f80f4
type-map.csv                               c201eed5aefbf8464b38c5eee2a7ada504  c201eed5aefbf8464b38c5eee2a7ada504
```
（更长前缀：`7cb4c053…32ff1` / `d9cc2746…0c0c7` / `65ee733d…eb15` / `7218eafc…3f7a` / `c201eed5…dbba`。
跨解释器同样成立：系统 Python 3.13.14 与旧仓 3.12.10 输出上述同一组 sha256。）

### 10.2 FTS5 触发器被自己的过滤条件滤掉（曾导致 SQLite 侧漏 3 个功能性对象）

**症状**：`schema.v0018.sqlite.sql` 里有虚表、有影子表，**没有** `document_chunk_ai/ad/au`。
**根因**：从 `sqlite_master` 挑对象时用了 `name.startswith("document_chunk_fts_")`，
而触发器名是 `document_chunk_ai/ad/au`（前缀是 `document_chunk_`，中间没有 `fts`）⇒ 全被过滤。
**修法**：触发器按「迁移里 `CREATE TRIGGER` 语句的名字集合」精确匹配，不再靠前缀猜。
**后果校正**：没有这 3 个触发器，external-content FTS5 **索引永远为空**（§3.2.1 有实测对比）。

> 🔴 **可迁移的教训（写 DDL 抽取器的人会重踩）**：**凡是「按键名前缀归类」的对象发现逻辑，
> 只要有一个对象族的命名不遵循该前缀，就一定会被静默吞掉**——不报错、不告警、不影响任何既有测试，
> 只在功能上表现为「检索永远返回 0 行」。
>
> 本例尤其阴险：虚表叫 `document_chunk_fts`、影子表叫 `document_chunk_fts_*`（都符合前缀），
> 唯独**同一段迁移里一起创建的** 3 个触发器叫 `document_chunk_ai/ad/au`（前缀是 `document_chunk_`）
> —— 差两个字符，肉眼扫一眼 `sqlite_master` 也容易漏。
>
> **防御规则**：①对象发现**不要**靠前缀猜，直接取「源 SQL 里出现的对象名」；
> ②对**必须存在**的对象做**硬断言**（本工具对 2 个 hnsw 就是这么做的：缺一个直接退出码 2）；
> ③再加一条**功能性**验证（本例：插一行 → `MATCH` 必须返回 1），静态计数挡住这一类漏项是不成立的。

### 10.3 影子表不能重放（`table ... already exists`）

**症状**：第一次跑 `export_ddl.py` 直接崩在 `sqlite3.OperationalError: table 'document_chunk_fts_config' already exists`。
**根因**：`CREATE VIRTUAL TABLE` 已**隐式**建出 4 张影子表，再把 `sqlite_master` 里读到的影子表 DDL
原样回放就撞车。
**修法**：影子表语句在 `.sql` 里以 `-- [sqlite_master] ...` **注释冻结**（权威文本不丢），
整份文件仍可 `executescript` 整段执行（§5 有对账输出）。

### 10.4 子包导入时裸 `import _env` 失败

**症状**：`run.py` 报 `skip optional module ddl.exporter: No module named '_env'`。
**根因**：CLI 只在 `if __package__ in (None, "")` 时把脚本目录插进 `sys.path`；
以 `ddl.exporter` 模块方式导入时 `__package__ == "ddl"`，裸 import 兄弟模块直接失败。
**修法**：无条件把脚本目录插入 `sys.path`（支持直跑与模块导入两种入口）。


---

## 11. 文件清单

```
scripts/extract-from-py/ddl/
├── __init__.py        # 让 run.py 按「可选子包」约定发现 ddl（1 行版本号，无副作用）
├── _env.py            # 环境解析（**全部委托** C-01 _bootstrap）+ 解释器守卫 + metadata 装载
├── _extract.py        # 三源抽取核心（AST 求值 / 内存 FTS5 物化 / 归一化 / SQL 渲染），纯函数
├── export_ddl.py      # CLI：生成 4 件套（含 --check）
├── gen_type_map.py    # CLI：生成 contracts/db/type-map.csv（含 --check）
├── exporter.py        # run.py 适配层：export(ctx) → 依次调上面两个 CLI（失败抛异常，不静默）
└── README.md          # 本文件

contracts/
├── schema.v0018.pg.sql
├── schema.v0018.pg.normalized.json
├── schema.v0018.sqlite.sql
├── schema.v0018.sqlite.normalized.json
└── db/type-map.csv
```

### 11.1 与 `run.py` 的接口

```bash
python scripts/extract-from-py/run.py export    # 全部抽取器（含 ddl）+ 重建 manifest.sha256 / contract-manifest.json
python scripts/extract-from-py/run.py check     # 台账比对
```

实测发现链：
```
registered: ['envelope', 'errors', 'migration', 'openapi', 'sse', 'ddl']
exporter payload: {'ddl_exit': 0, 'type_map_exit': 0, 'out_dir': 'D:\\WBT\\WBTimeAI\\contracts'}
```


产物禁止手改：任何改动都会让 `--check` 变红。sha256 台账由 C-07（`contract-manifest.json`）统一登记，
本文件不写死 hash（会随重抽漂移，写死即误导）。
