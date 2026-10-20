// ---------------------------------------------------------------------------
// WBTimeAI · conversationService 单测（V0.4.5 B3 · F-09 会话重命名）
//
// 覆盖新增方法 `update(id, { title })`：命中 `PUT /conversations/{id}`，
// 且以 `{ title }` 为请求体、解析统一响应壳返回更新后的会话 DTO。
// 以 msw 打桩冻结契约（断言请求命中的**方法 + 路径 + 请求体**）。
// ---------------------------------------------------------------------------
import { http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { conversationService } from "@/services/conversation";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

interface Seen {
  method: string;
  path: string;
  body: unknown;
}

describe("conversationService.update（F-09 会话重命名）", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("命中 PUT /conversations/{id} 并返回更新后的会话", async () => {
    const seen: Seen = { method: "", path: "", body: null };
    server.use(
      http.put("/api/v1/conversations/:conversationId", async ({ request }) => {
        const url = new URL(request.url);
        seen.method = request.method;
        seen.path = url.pathname;
        seen.body = await request.json();
        return shell({
          id: "conv-1",
          tenant_id: "t1",
          workspace_id: "w1",
          agent_id: "a1",
          user_id: "u1",
          title: "追加 V0.4.5 测试问题",
          status: "ACTIVE",
        });
      }),
    );

    const result = await conversationService.update("conv-1", { title: "追加 V0.4.5 测试问题" });

    expect(result.title).toBe("追加 V0.4.5 测试问题");
    expect(seen).toMatchObject({
      method: "PUT",
      path: "/api/v1/conversations/conv-1",
      body: { title: "追加 V0.4.5 测试问题" },
    });
  });
});
