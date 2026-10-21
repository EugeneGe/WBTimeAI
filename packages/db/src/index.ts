/**
 * @wbtime/db —— V0.1.0 数据层出口。
 *
 * 三个子出口：
 * * ``@wbtime/db/schema``      —— drizzle 双档表对象（生成物，禁手改）
 * * ``@wbtime/db/repositories``—— ScopedRepo 泛型仓储（手写，scope 纪律所在）
 * * ``@wbtime/db/connection``  —— 连接工厂（**刻意不进根出口**：`connection.ts` 顶层
 *   `import { DatabaseSync } from "node:sqlite"`，一旦从根出口透出，任何 `import "@wbtime/db"`
 *   的进程都会在**加载期**被要求 `--experimental-sqlite`）
 * * 根出口同时暴露 schema 与 repositories（schema 用命名空间 ``pg`` / ``sqlite`` 隔离，避免方言串味）
 *
 * V0.2.0（T2-05）新增 `./seed/permissions.js`（权限码字典 bootstrap 种子）：
 * 它只写**数据行**、零 DDL，且不 import `node:sqlite`，因此可以安全地从根出口透出。
 */

export * as pg from "./schema/pg/index.js";
export * as sqlite from "./schema/sqlite/index.js";
export { SCHEMA_VERSION, TABLES, GENERATED_COUNTS } from "./schema/model.js";
export * from "./repositories/index.js";
export * from "./seed/permissions.js";
export * from "./vector-support.js";
