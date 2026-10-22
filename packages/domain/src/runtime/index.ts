// @wbtime/domain · runtime 子域出口（T3-04）。
//
// 五个纯域模块 + 五个端口签名。**零 ORM / 零 Web / 零运行时依赖**。
// 端口签名为 W1 首日冻结面：T3-02 / T3-09 / T3-10 引用后不得改签名（只许新增端口）。

export * from "./run-status.js";
export * from "./run-stop-reason.js";
export * from "./run-state.js";
export * from "./tool-call-state.js";
export * from "./budget-ledger.js";
export * from "./ports.js";
// V0.3.1 · G031-SPK：子 Agent 委派的域常量（零 DDL 标记值；只新增导出，不改既有结构）。
export * from "./subagent.js";
