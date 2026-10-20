/**
 * @wbtime/db —— V0.1.0 数据层出口。
 *
 * 三个子出口：
 * * ``@wbtime/db/schema``      —— drizzle 双档表对象（生成物，禁手改）
 * * ``@wbtime/db/repositories``—— ScopedRepo 泛型仓储（手写，scope 纪律所在）
 * * 根出口同时暴露两者（schema 用命名空间 ``pg`` / ``sqlite`` 隔离，避免方言串味）
 */

export * as pg from "./schema/pg/index.js";
export * as sqlite from "./schema/sqlite/index.js";
export { SCHEMA_VERSION, TABLES, GENERATED_COUNTS } from "./schema/model.js";
export * from "./repositories/index.js";
export * from "./vector-support.js";
