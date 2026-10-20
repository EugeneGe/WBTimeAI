// 由 scripts/gen-drizzle-schema.mjs 生成 —— **禁止手改**。
// pgvector 的 `vector(1536)` 无 drizzle 内建列类型，故用 customType **精确**发出该类型串。
//
// 🔴 ORM 编译**不会**自己产生 hnsw 索引（旧线已知缺陷）。那 2 个 hnsw 由 model.ts 的
//    PG_RAW_INDEXES 原样搬运，并由 scripts/check_drizzle_parity.py 显式断言「恰好 2 个」。
import { customType } from "drizzle-orm/pg-core";

/** `vector(1536)` —— emit 原文见 contracts/db/type-map.csv 的 `VectorType()` 行。 */
export const vector1536 = customType<{ data: number[]; driverData: string }>({
  dataType() {
    return "vector(1536)";
  },
});
