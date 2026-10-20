// ---------------------------------------------------------------------------
// E6 回归：`toApiError` 幂等化（QA OBS-3）
//
// 响应拦截器已把错误归一为 `ApiError`；各页 `onError` 又调 `toApiError(error)` →
// 二次归一曾吞掉服务端 `message`（恒「未知错误」）。修复后：已是 `ApiError` 形状 → 原样返回。
// ---------------------------------------------------------------------------
import { describe, expect, it } from "vitest";

import { toApiError } from "@/lib/api";
import type { ApiError } from "@/types";

describe("toApiError idempotency (E6)", () => {
  it("passes through an already-normalized ApiError (message 透传、同一引用)", () => {
    const normalized: ApiError = {
      code: "NOT_FOUND",
      message: "运行环境不存在",
      data: { environment_id: "env-1" },
      status: 404,
    };

    const result = toApiError(normalized);
    expect(result).toBe(normalized);
    expect(result.message).toBe("运行环境不存在");
    expect(result.code).toBe("NOT_FOUND");
  });

  it("keeps normalizing non-normalized inputs unchanged", () => {
    expect(toApiError(new Error("boom"))).toEqual({
      code: "CLIENT_ERROR",
      message: "boom",
      data: {},
    });
    expect(toApiError(undefined)).toEqual({
      code: "UNKNOWN_ERROR",
      message: "未知错误",
      data: {},
    });
  });
});
