/**
 * Phase 2c / W8（T2-44）：Marketplace 前端 DTO（设计 §2.13.1；裁定 R5 / R14）。
 *
 * 与后端 `apps/api/src/wbtime_ai_api/schemas/marketplace.py` 严格对齐；全路径
 * `/api/v1/agent-studio/marketplace/*`，统一响应壳由 `lib/api.ts` 拦截器解壳。
 *
 * 🔴 R14：前端**不解析 yaml**（不引入 `js-yaml`）——上传 **yaml 原文**，元数据由**后端**返回；
 *    导出为**规范化 yaml 文本**（前端仅展示 / 下载）。
 */

/** 可发布包的三类资源（↔ `wbtime-ai-package.yaml` 的 `kind`）。 */
export type WBTimeAIPackageKind = "agent" | "skill" | "workflow";

/** 三类资源（有序，供导出下拉渲染）。 */
export const WBTIME_AI_PACKAGE_KINDS: readonly WBTimeAIPackageKind[] = [
  "agent",
  "skill",
  "workflow",
] as const;

/** 导入请求（`POST /agent-studio/marketplace/import`）。 */
export interface MarketplaceImportRequest {
  /** 包清单 **yaml 原文**（R14：前端上传文本，不解析）。 */
  package_yaml: string;
  /** 期望的归档摘要（可选；提供则后端校验，不匹配拒绝）。 */
  expected_sha256?: string | null;
  /** `false` = 预检（仅返回元数据）；`true` = 确认导入（落库）。 */
  confirm: boolean;
}

/** 预检结果（`confirm=false`）——安装前展示的元数据。 */
export interface MarketplacePreview {
  status: "PREVIEW";
  kind: string;
  name: string;
  version: string;
  core_compat: string;
  author: string;
  license: string;
  /** 依赖清单（字符串引用）。 */
  dependencies: string[];
  /** 资源清单相对路径。 */
  manifest_path: string;
  /** 归档摘要（SHA-256）。 */
  artifact_sha256: string;
  /** 是否携带签名（`false` → 前端展示「未签名」）。 */
  signature_present: boolean;
}

/** 导入结果（`confirm=true`）。 */
export interface MarketplaceImportResult {
  status: "IMPORTED";
  kind: string;
  name: string;
  version: string;
  /** 落库后内容摘要。 */
  digest: string;
}

/** 导入响应（预检 / 导入二态）。 */
export type MarketplaceImportResponse = MarketplacePreview | MarketplaceImportResult;

/** 导出响应（`GET /agent-studio/marketplace/export`）。 */
export interface MarketplaceExportResponse {
  /** 规范化 yaml 文本。 */
  yaml: string;
  kind: string;
  id: string;
  /** 内容摘要。 */
  digest: string;
}

/** 类型守卫：判定导入响应是否为**预检**结果。 */
export function isMarketplacePreview(
  response: MarketplaceImportResponse,
): response is MarketplacePreview {
  return response.status === "PREVIEW";
}

/** 类型守卫：判定导入响应是否为**导入完成**结果。 */
export function isMarketplaceImportResult(
  response: MarketplaceImportResponse,
): response is MarketplaceImportResult {
  return response.status === "IMPORTED";
}
