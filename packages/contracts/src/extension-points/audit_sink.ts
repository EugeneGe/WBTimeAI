/**
 * ExtensionPoint ③ `audit_sink`（审计落点）—— interface 声明（纯类型，无 loader）。
 *
 * **E-3 锚点**：路线图 §3.1 M-05 E-3 要求「`audit.Sink` 与 `contracts.audit_sink/v1`
 * 签名全等」。本接口是三面对齐中的 **TS 面**，另两面是旧线：
 *
 * - 插件面：`packages/plugin/src/wbtime_ai_plugin/extension_points/audit_sink.py:17,21-34`
 * - 核心面：`packages/audit/src/wbtime_ai_audit/sink.py:59-72`（E-3 原文指 `audit/sink.py:5` 的
 *   `AuditSink` Protocol；Protocol 体实测在 `:59`，`:5` 是模块 docstring 的对齐声明行）
 *
 * 三面由 `scripts/check_extension_point_signatures.py` 逐成员断言（方法名 + 参数个数 + 返回类型）。
 *
 * 🔴 `write()` 抛异常时，核心须**降级本地落盘 + 告警**，**不静默丢弃**（旧线 §2.18）——
 *    该降级属运行面，归 V0.7.0，本文件只声明契约。
 * 🔴 成员名沿用旧线 snake_case；无 loader / 无注册 / 无签名校验。
 */

import type { AuditEvent, SinkHealth } from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const AUDIT_SINK_VERSION = "audit_sink/v1";

/** 审计落点扩展点（SIEM / 外部审计系统）。 */
export interface AuditSink {
  /** 写入一条审计事件；失败须由调用方降级，**不得静默**。 */
  write(event: AuditEvent): void;
  /** 刷写缓冲（落盘 / 远端提交）。 */
  flush(): void;
  /** 报告落点健康状态。 */
  health(): SinkHealth;
}
