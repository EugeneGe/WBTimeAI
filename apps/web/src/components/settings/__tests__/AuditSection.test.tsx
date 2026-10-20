// ---------------------------------------------------------------------------
// WBTimeAI · 设置·系统·审计区块单测（V0.4.6 收口 · M07-01 第 12 条）
//
// 覆盖：
//   ① 只读流水渲染：时间（稳定格式）/ 主体（user / Agent / 「—」）/ 动作 / 资源 / 结果徽标；
//   ② 顶部数据范围提示存在（L-1 修复后为「服务端过滤 + 分页作用全量记录」）；
//   ③ 空态；
//   ④ 错误态区分 401 / 403 文案（其余通用）；
//   ⑤ 过滤条把 `action` / `user_id` 送入请求，分页以 `limit` + `offset` 步进。
//
// 全部以 `server.use` 内联打桩（不改 `src/test/msw-handlers.ts`）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { AuditSection } from "@/components/settings/AuditSection";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";
import type { AuditLogResponse } from "@/types";

/** 审计夹具：用户主体 / Agent 主体 / 双空主体；SUCCESS / FAILURE / 其他结果。 */
const LOGS: AuditLogResponse[] = [
  {
    id: "a1",
    tenant_id: "t1",
    user_id: "u1",
    agent_id: null,
    run_id: null,
    action: "tool.invoke",
    resource_type: "tool",
    resource_id: "t-1",
    outcome: "SUCCESS",
    duration_ms: 12,
    request_id: "r1",
    created_at: "2026-01-02T03:04:05.678Z",
  },
  {
    id: "a2",
    tenant_id: "t1",
    user_id: null,
    agent_id: "ag1",
    run_id: "run1",
    action: "workflow.run",
    resource_type: "workflow",
    resource_id: "w-1",
    outcome: "FAILURE",
    duration_ms: 900,
    request_id: "r2",
    created_at: null,
  },
  {
    id: "a3",
    tenant_id: "t1",
    user_id: null,
    agent_id: null,
    run_id: null,
    action: "",
    resource_type: null,
    resource_id: null,
    outcome: "PARTIAL",
    duration_ms: null,
    request_id: null,
    created_at: null,
  },
];

/** 按条数造审计记录（`id` 唯一；用于「下一页可用」的分页用例）。 */
function makeLogs(count: number): AuditLogResponse[] {
  return Array.from({ length: count }, (_, index) => ({
    ...LOGS[0],
    id: `p${index}`,
    action: `action.${index}`,
    created_at: "2026-01-02T03:04:05.000Z",
  }));
}

/** 渲染审计区块（独立 QueryClient；禁用重试）。 */
function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AuditSection />
    </QueryClientProvider>,
  );
}

describe("AuditSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.getState().setSession({ accessToken: "test", refreshToken: "test-refresh" });
  });

  it("只读流水：时间 / 主体（含 Agent 标注与「—」）/ 资源 / 结果徽标", async () => {
    server.use(http.get("/api/v1/audit", () => shell(LOGS)));
    renderSection();

    expect(await screen.findByTestId("settings-audit-table")).toBeInTheDocument();

    // 时间：稳定格式（不依赖运行环境 locale）。
    expect(screen.getByTestId("settings-audit-row-a1")).toHaveTextContent("2026-01-02 03:04:05");
    // 主体：user / Agent（标注）/ 双空 → 「—」。
    expect(screen.getByTestId("settings-audit-subject-a1")).toHaveTextContent("u1");
    expect(screen.getByTestId("settings-audit-subject-a2")).toHaveTextContent("Agent");
    expect(screen.getByTestId("settings-audit-subject-a2")).toHaveTextContent("ag1");
    expect(screen.getByTestId("settings-audit-subject-a3")).toHaveTextContent("—");
    // 资源：type · id；双空 → 「—」。
    expect(screen.getByTestId("settings-audit-row-a1")).toHaveTextContent("tool · t-1");
    expect(screen.getByTestId("settings-audit-row-a3")).toHaveTextContent("—");
    // 结果：SUCCESS 绿 / FAILURE 红 / 其他中性。
    expect(screen.getByTestId("settings-audit-outcome-a1")).toHaveTextContent("SUCCESS");
    expect(screen.getByTestId("settings-audit-outcome-a1")).toHaveClass("text-emerald-700");
    expect(screen.getByTestId("settings-audit-outcome-a2")).toHaveTextContent("FAILURE");
    expect(screen.getByTestId("settings-audit-outcome-a2")).toHaveClass("text-destructive");
    expect(screen.getByTestId("settings-audit-outcome-a3")).toHaveTextContent("PARTIAL");
    expect(screen.getByTestId("settings-audit-outcome-a3")).toHaveClass("text-muted-foreground");
  });

  it("顶部说明「服务端过滤 + 分页作用全量记录」（L-1 修复后不再提示窗口截断）", async () => {
    server.use(http.get("/api/v1/audit", () => shell(LOGS)));
    renderSection();

    await screen.findByTestId("settings-audit-table");
    const note = screen.getByTestId("settings-audit-note");
    // V0.4.6 缺陷 L-1 修复后：过滤/分页均下推服务端，旧文案「内存过滤」已不成立。
    expect(note).toHaveTextContent("服务端");
    expect(note).toHaveTextContent("200");
    expect(note).not.toHaveTextContent("内存过滤");
  });

  it("空态：无记录文案", async () => {
    server.use(http.get("/api/v1/audit", () => shell([])));
    renderSection();

    expect(await screen.findByTestId("settings-audit-empty")).toBeInTheDocument();
    expect(screen.getByText("暂无审计记录")).toBeInTheDocument();
  });

  it("401 → 登录失效文案（区别于 403）", async () => {
    // 401 后 `lib/api.ts` 会 `clearSession()` + 跳 `/login`；把 pathname 预置为 `/login`
    // 以**短路**该跳转（jsdom 未实现 navigation，避免无意义的未实现告警）。
    window.history.pushState({}, "", "/login");
    server.use(
      // 401 会触发一次单飞 refresh（`lib/api.ts`）→ 换新令牌后**重试一次**仍 401。
      http.post("/api/v1/auth/refresh", () =>
        shell({
          access_token: "refreshed",
          refresh_token: "refreshed-refresh",
          token_type: "bearer",
          expires_in: 3600,
        }),
      ),
      http.get("/api/v1/audit", () =>
        HttpResponse.json({ code: "UNAUTHORIZED", message: "未认证", data: {} }, { status: 401 }),
      ),
    );
    renderSection();

    const errorBox = await screen.findByTestId("settings-audit-error");
    expect(errorBox).toHaveTextContent("登录状态已失效");
    expect(errorBox).not.toHaveTextContent("无权");
    window.history.pushState({}, "", "/");
  });

  it("403 → 无权限文案（区别于 401）", async () => {
    server.use(
      http.get("/api/v1/audit", () =>
        HttpResponse.json({ code: "FORBIDDEN", message: "无权访问", data: {} }, { status: 403 }),
      ),
    );
    renderSection();

    const errorBox = await screen.findByTestId("settings-audit-error");
    expect(errorBox).toHaveTextContent("无权查看审计记录");
    expect(errorBox).not.toHaveTextContent("登录状态已失效");
  });

  it("过滤把 action / user_id 送入请求；分页以 limit + offset 步进", async () => {
    const searches: URLSearchParams[] = [];
    server.use(
      http.get("/api/v1/audit", ({ request }) => {
        searches.push(new URL(request.url).searchParams);
        return shell(LOGS);
      }),
    );
    renderSection();

    await screen.findByTestId("settings-audit-table");
    // 首页：limit=20 & offset=0（未设置过滤参数）。
    expect(searches[0].get("limit")).toBe("20");
    expect(searches[0].get("offset")).toBe("0");
    expect(searches[0].get("action")).toBeNull();

    fireEvent.change(screen.getByTestId("settings-audit-filter-action"), {
      target: { value: "tool.invoke" },
    });
    fireEvent.change(screen.getByTestId("settings-audit-filter-user"), {
      target: { value: "u1" },
    });
    fireEvent.click(screen.getByTestId("settings-audit-filter-apply"));

    await waitFor(() => {
      const last = searches[searches.length - 1];
      expect(last.get("action")).toBe("tool.invoke");
      expect(last.get("user_id")).toBe("u1");
      expect(last.get("offset")).toBe("0");
    });

    // 结果不足一页（3 < 20）→ 「下一页」禁用；「上一页」在首页禁用。
    expect(screen.getByTestId("settings-audit-next")).toBeDisabled();
    expect(screen.getByTestId("settings-audit-prev")).toBeDisabled();
    expect(screen.getByTestId("settings-audit-page")).toHaveTextContent("第 1 页");
  });

  it("先翻到第 2 页再点「查询」→ 回到第 1 页（offset 归零）", async () => {
    const offsets: string[] = [];
    server.use(
      http.get("/api/v1/audit", ({ request }) => {
        const params = new URL(request.url).searchParams;
        offsets.push(String(params.get("offset")));
        // 整页 20 条 → 「下一页」可用。
        return shell(makeLogs(20));
      }),
    );
    renderSection();

    await screen.findByTestId("settings-audit-table");
    fireEvent.click(screen.getByTestId("settings-audit-next"));
    await waitFor(() => {
      expect(screen.getByTestId("settings-audit-page")).toHaveTextContent("第 2 页");
    });
    expect(offsets[offsets.length - 1]).toBe("20");

    // 第 2 页上点「查询」→ page 复位 0。
    fireEvent.change(screen.getByTestId("settings-audit-filter-action"), {
      target: { value: "tool.invoke" },
    });
    fireEvent.click(screen.getByTestId("settings-audit-filter-apply"));

    await waitFor(() => {
      expect(screen.getByTestId("settings-audit-page")).toHaveTextContent("第 1 页");
    });
    expect(offsets[offsets.length - 1]).toBe("0");
  });

  it("500 → 走通用错误文案（区别于 401 / 403）", async () => {
    server.use(
      http.get("/api/v1/audit", () =>
        HttpResponse.json(
          { code: "INTERNAL_ERROR", message: "服务内部错误", data: {} },
          { status: 500 },
        ),
      ),
    );
    renderSection();

    const errorBox = await screen.findByTestId("settings-audit-error");
    expect(errorBox).toHaveTextContent("审计记录加载失败");
    // 通用分支附带后端 message（便于排查）。
    expect(errorBox).toHaveTextContent("服务内部错误");
    expect(errorBox).not.toHaveTextContent("登录状态已失效");
    expect(errorBox).not.toHaveTextContent("无权");
  });
});
