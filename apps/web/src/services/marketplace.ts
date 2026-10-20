import { api } from "@/lib/api";
import type {
  MarketplaceExportResponse,
  MarketplaceImportRequest,
  MarketplaceImportResponse,
} from "@/types";

/**
 * Marketplace 服务（`/agent-studio/marketplace/*` API，W8 / T2-44；设计 §2.13.1）。
 *
 * - **导入**：上传 **yaml 原文**（`confirm=false` 预检元数据 / `confirm=true` 落库）；
 * - **导出**：按 `kind` + `id` 取**规范化 yaml 文本**。
 *
 * 🔴 R14：前端**不解析 yaml**（元数据由**后端**返回；不引入 `js-yaml` / 任何新依赖）。
 * 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 */
export const marketplaceService = {
  /** 导入包：`confirm=false` 预检元数据；`confirm=true` 确认导入（落库）。 */
  importPackage(payload: MarketplaceImportRequest): Promise<MarketplaceImportResponse> {
    return api
      .post<MarketplaceImportResponse>("/agent-studio/marketplace/import", payload)
      .then((r) => r.data);
  },
  /**
   * 导出包：按 `kind` + `id` 返回规范化 yaml 文本。
   *
   * ⚠️ **路由暂不可达（V0.4.6 缺陷 L-3 · 保留能力）**：唯一消费页 `pages/Marketplace.tsx`
   * 已被 `router.tsx` 重定向到 `/agents?tab=skills`，故当前 UI 无法到达此调用点。
   * **保留** service 与其测试，供后续 Marketplace 页回归时直接复用；**不要删除**。
   */
  exportPackage(params: { kind: string; id: string }): Promise<MarketplaceExportResponse> {
    return api
      .get<MarketplaceExportResponse>("/agent-studio/marketplace/export", { params })
      .then((r) => r.data);
  },
};
