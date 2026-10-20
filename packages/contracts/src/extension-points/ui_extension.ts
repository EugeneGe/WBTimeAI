/**
 * ExtensionPoint ⑧ `ui_extension`（前端扩展点）—— interface 声明（纯类型，无 loader）。
 *
 * 证据（旧线，只读归档 `D:/WBT/WBTimeAI_old`）：
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/ui_extension.py:12`（版本常量）
 * `packages/plugin/src/wbtime_ai_plugin/extension_points/ui_extension.py:16-25`（`UIExtension` Protocol）
 *
 * 🔴 成员名沿用旧线 snake_case；本文件**不含**任何运行面。
 */

import type { UISlot } from "../domain-refs.js";

/** 扩展点版本（格式 `<point>/vN`；与旧线 `EXTENSION_POINT_VERSION` 全等）。 */
export const UI_EXTENSION_VERSION = "ui_extension/v1";

/** 前端扩展点（插槽声明 + 静态资源基址）。 */
export interface UIExtension {
  /** 声明 UI 插槽清单。 */
  slots(): UISlot[];
  /** 静态资源基址（空串表示无外部资源）。 */
  assets_base_url(): string;
}
