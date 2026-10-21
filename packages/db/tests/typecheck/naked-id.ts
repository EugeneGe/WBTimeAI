/**
 * J-8 夹具 · **必须编译失败**。
 *
 * 这个文件是「反例」而不是「示例」：它故意用裸 `string` 去调
 * `repo.findById(...)`，`ScopedRepo.findById(ref: ScopedRef)` 只接受带品牌
 * （未导出的 `unique symbol`）的 `ScopedRef`，而 `ScopedRef` 只能由
 * `Scope#ref(id)` 生产 —— 所以下面那一行在**类型层**就过不去。
 *
 * 判据（`run.mjs` 执行并断言）：
 *   * `tsc --noEmit -p tests/typecheck/tsconfig.json` 的 **exit code != 0**；
 *   * 输出必须点名 `naked-id.ts` 且提到 `ScopedRef`（即错在**参数品牌**上，
 *     而不是"文件里别的地方写错了"）；
 *   * `error TS` 恰好 1 条（防止"反例顺手带出别的错"让判据假绿）。
 *
 * 若哪天这里**能编译通过**了，说明 I-1 的类型约束被削弱（例如有人把
 * `ScopedRef` 改成 `string` 别名，或给 `findById` 加了 `string` 重载）——
 * 那时 J-8 会红，而红得正确。
 */

import { Scope, UserRepo } from "../../src/repositories/index.js";
import type { DrizzleDatabase } from "../../src/repositories/index.js";

// 只为了构造一个真实类型的仓储实例；`undefined` 转型不会引入额外诊断。
const db = undefined as unknown as DrizzleDatabase;
const scope = new Scope("tenant-a");
const repo = new UserRepo(db, scope, "sqlite");

/** 反例本体：裸 id。 */
export function violatesNakedIdBan(): void {
  // 本文件**不出现**任何抑制指令（ts-ignore / ts-expect-error）：一旦抑制，
  // 判据就变成"自证清白"——反例会"通过"，而真正该红的错误被藏起来。
  void repo.findById("some-id"); // ← 这一行**必须**报 TS2345
}

/** 正向对照：`Scope#ref()` 产出的引用可以正常通过（证明报错来自品牌，不是别的）。 */
export async function allowedPath(): Promise<void> {
  await repo.findById(scope.ref("some-id"));
}
