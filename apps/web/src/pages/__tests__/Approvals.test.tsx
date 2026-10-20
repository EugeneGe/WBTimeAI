// ---------------------------------------------------------------------------
// WBTimeAI · Approvals 单测（W10 / T2-49 契约：`/approvals` 四端点前端接入）
//
// 覆盖：
//   ① 列表渲染（subject_type 中文名 + 请求人 + 相对时间）；
//   ② 选中条目 → 右列详情切换（请求人 / 提交时间 / 载荷预览）；
//   ③ 「通过」→ 失效列表 → 该条离开待办（列表刷新）；
//   ④ 「驳回」**必须二次确认**：弹窗出现且未点确认时**不发请求**；
//   ⑤ 空态（`GET /approvals` 返回 `[]`）；
//   ⑥ 请求失败 → 错误面板展示后端 `message` + 重试；
//   ⑦ 决议 409（已决议）→ 就地展示后端 `message`。
//
// 打桩口径：全部经 `server.use(...)` **内联**（不改共享 `src/test/msw-handlers.ts`）；
// 页面使用 `useNavigate` 之外无路由依赖，但统一包 `MemoryRouter` 以防后续演进。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { Approvals } from "@/pages/Approvals";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

// Radix Dialog 依赖的 jsdom 缺失 API（指针捕获 / 滚动 / ResizeObserver）。
beforeAll(() => {
  const proto = Element.prototype as Element & {
    hasPointerCapture?: (pointerId: number) => boolean;
    setPointerCapture?: (pointerId: number) => void;
    releasePointerCapture?: (pointerId: number) => void;
  };
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = () => false;
  }
  if (typeof proto.setPointerCapture !== "function") {
    proto.setPointerCapture = () => {};
  }
  if (typeof proto.releasePointerCapture !== "function") {
    proto.releasePointerCapture = () => {};
  }
  if (typeof HTMLElement.prototype.scrollIntoView !== "function") {
    HTMLElement.prototype.scrollIntoView = () => {};
  }
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver;
  }
});

/** 待办审批夹具（`ApprovalResponse`；`workflow_node` 主体）。 */
const APPROVAL_A = {
  id: "ap1",
  tenant_id: "t1",
  subject_type: "workflow_node",
  subject_ref: "wf1:node-human-approval",
  requested_by: "u-requester",
  status: "PENDING",
  decided_by: null,
  decided_at: null,
  payload: { node: "human_approval", message: "请审批该节点" },
  expires_at: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
};

/** 待办审批夹具（`tool` 主体；验证主体类型中文名切换）。 */
const APPROVAL_B = {
  ...APPROVAL_A,
  id: "ap2",
  subject_type: "tool",
  subject_ref: "tool-call-2",
  requested_by: "u-second",
};

/** 当前后端「待办」返回集（决议后由 handler 就地移除，模拟真实列表刷新）。 */
let pending: Array<Record<string, unknown>> = [];

/** 决议端点调用计数（断言「未确认不发请求」）。 */
let approveCalls = 0;
let rejectCalls = 0;

/** 渲染 Approvals（独立 QueryClient，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/approvals"]}>
        <Approvals />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 注册待办列表 / 详情 / 决议三组契约 handler（默认成功路径）。 */
function stubApprovalApi(): void {
  server.use(
    http.get("/api/v1/approvals", () => shell(pending)),
    http.get("/api/v1/approvals/:approvalId", ({ params }) => {
      const approvalId = String(params.approvalId);
      const found = pending.find((item) => item.id === approvalId);
      if (!found) {
        return HttpResponse.json(
          { code: "NOT_FOUND", message: "审批不存在", data: {}, request_id: "test" },
          { status: 404 },
        );
      }
      return shell(found);
    }),
    http.post("/api/v1/approvals/:approvalId/approve", ({ params }) => {
      approveCalls += 1;
      const approvalId = String(params.approvalId);
      const found = pending.find((item) => item.id === approvalId);
      pending = pending.filter((item) => item.id !== approvalId);
      return shell({ ...(found ?? APPROVAL_A), id: approvalId, status: "APPROVED" });
    }),
    http.post("/api/v1/approvals/:approvalId/reject", ({ params }) => {
      rejectCalls += 1;
      const approvalId = String(params.approvalId);
      const found = pending.find((item) => item.id === approvalId);
      pending = pending.filter((item) => item.id !== approvalId);
      return shell({ ...(found ?? APPROVAL_A), id: approvalId, status: "REJECTED" });
    }),
  );
}

describe("Approvals", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
    pending = [{ ...APPROVAL_A }, { ...APPROVAL_B }];
    approveCalls = 0;
    rejectCalls = 0;
    stubApprovalApi();
  });

  it("渲染待办列表与详情（主体类型 / 请求人 / 载荷预览）", async () => {
    renderPage();

    expect(await screen.findByTestId("approvals-page")).toBeInTheDocument();
    expect(await screen.findByTestId("approval-item-ap1")).toHaveTextContent("工作流节点");
    expect(screen.getByTestId("approval-item-ap1")).toHaveTextContent("u-requester");
    expect(screen.getByTestId("approval-item-ap2")).toHaveTextContent("工具调用");
    // 页头计数副标题。
    expect(screen.getByTestId("approvals-subtitle")).toHaveTextContent("2 条待办");

    // 默认选中第一条 → 详情已就绪。
    const detail = await screen.findByTestId("approvals-detail");
    expect(detail).toHaveTextContent("u-requester");
    expect(screen.getByTestId("approval-payload")).toHaveTextContent("human_approval");
    // 载荷**默认收起**（折叠 JSON 预览，点击展开）。
    expect(screen.getByTestId("approval-payload")).not.toHaveAttribute("open");
  });

  it("选中另一条 → 详情切换", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("approval-item-ap2"));

    await waitFor(() =>
      expect(screen.getByTestId("approvals-detail")).toHaveTextContent("u-second"),
    );
    expect(screen.getByTestId("approval-subject-type")).toHaveTextContent("工具调用");
  });

  it("通过 → 列表刷新（该条离开待办）", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("approval-approve"));

    await waitFor(() => expect(screen.queryByTestId("approval-item-ap1")).toBeNull());
    expect(screen.getByTestId("approval-item-ap2")).toBeInTheDocument();
    expect(approveCalls).toBe(1);
  });

  it("驳回需二次确认：确认前不发请求", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("approval-reject"));

    const dialog = await screen.findByTestId("approval-reject-dialog");
    expect(dialog).toHaveTextContent("确认驳回");
    expect(rejectCalls).toBe(0);

    fireEvent.click(screen.getByTestId("approval-reject-confirm"));

    await waitFor(() => expect(rejectCalls).toBe(1));
    await waitFor(() => expect(screen.queryByTestId("approval-item-ap1")).toBeNull());
  });

  it("空态：无待办时展示内联空态", async () => {
    pending = [];
    renderPage();

    expect(await screen.findByTestId("approvals-empty")).toHaveTextContent("暂无待办审批");
    expect(screen.getByTestId("approvals-subtitle")).toHaveTextContent("0 条待办");
    expect(screen.queryByTestId("approvals-detail")).toBeNull();
    expect(screen.getByTestId("approvals-detail-placeholder")).toBeInTheDocument();
  });

  it("请求失败 → 错误面板展示后端 message 并可重试", async () => {
    server.use(
      http.get("/api/v1/approvals", () =>
        HttpResponse.json(
          {
            code: "INTERNAL_ERROR",
            message: "审批服务暂不可用",
            data: {},
            request_id: "test",
          },
          { status: 500 },
        ),
      ),
    );
    renderPage();

    const panel = await screen.findByTestId("approvals-list-error");
    expect(panel).toHaveTextContent("审批服务暂不可用");
    expect(screen.getByTestId("approvals-retry")).toBeInTheDocument();
  });

  it("决议 409（已决议）→ 就地展示后端 message", async () => {
    server.use(
      http.post("/api/v1/approvals/:approvalId/approve", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "审批已决议，不可重复决议",
            data: { approval_id: "ap1" },
            request_id: "test",
          },
          { status: 409 },
        ),
      ),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("approval-approve"));

    expect(await screen.findByTestId("approval-feedback")).toHaveTextContent(
      "审批已决议，不可重复决议",
    );
  });

  it("决议反馈不串记录：通过 ap1 后切到 ap2 不残留该反馈（P2-1）", async () => {
    // 列表两条待办同时存在（决议后列表仍返回两条，模拟列表刷新滞后于详情切换），
    // 用于验证 `ApprovalDetail` 按 `approvalId` **重挂载**：`feedback` 等局部状态不跨记录泄漏。
    server.use(
      http.get("/api/v1/approvals", () => shell([{ ...APPROVAL_A }, { ...APPROVAL_B }])),
      http.post("/api/v1/approvals/:approvalId/approve", ({ params }) =>
        shell({ ...APPROVAL_A, id: String(params.approvalId), status: "APPROVED" }),
      ),
    );
    renderPage();

    // 默认选中 ap1 → 通过 → 出现「已通过」反馈。
    fireEvent.click(await screen.findByTestId("approval-approve"));
    expect(await screen.findByTestId("approval-feedback")).toHaveTextContent("已通过");

    // 切到 ap2 → 反馈**不得**残留，且 ap2 的决议按钮仍可用（未被误判为已决议）。
    fireEvent.click(screen.getByTestId("approval-item-ap2"));
    await waitFor(() =>
      expect(screen.getByTestId("approval-subject-type")).toHaveTextContent("工具调用"),
    );
    expect(screen.queryByTestId("approval-feedback")).toBeNull();
    expect(screen.getByTestId("approval-approve")).toBeEnabled();
    expect(screen.getByTestId("approval-reject")).toBeEnabled();
  });

  it("详情已 APPROVED（详情端点无状态过滤）→ 只读态，不渲染决议按钮", async () => {
    server.use(
      http.get("/api/v1/approvals", () => shell([{ ...APPROVAL_A }])),
      http.get("/api/v1/approvals/:approvalId", () =>
        shell({
          ...APPROVAL_A,
          status: "APPROVED",
          decided_by: "u-approver",
          decided_at: "2026-10-13T01:00:00Z",
        }),
      ),
    );
    renderPage();

    const readonly = await screen.findByTestId("approval-readonly");
    expect(readonly).toHaveTextContent("该审批已决议，仅供查看");
    expect(screen.getByTestId("approval-decided-by")).toHaveTextContent("u-approver");
    expect(screen.getByTestId("approval-status")).toHaveTextContent("已通过");
    // 已决议 → 决议按钮**不渲染**。
    expect(screen.queryByTestId("approval-approve")).toBeNull();
    expect(screen.queryByTestId("approval-reject")).toBeNull();
  });

  it("详情已 EXPIRED → 「已过期」提示且决议按钮禁用", async () => {
    server.use(
      http.get("/api/v1/approvals", () => shell([{ ...APPROVAL_A }])),
      http.get("/api/v1/approvals/:approvalId", () => shell({ ...APPROVAL_A, status: "EXPIRED" })),
    );
    renderPage();

    expect(await screen.findByTestId("approval-expired-hint")).toHaveTextContent("已过期");
    expect(screen.getByTestId("approval-status")).toHaveTextContent("已过期");
    expect(screen.getByTestId("approval-approve")).toBeDisabled();
    expect(screen.getByTestId("approval-reject")).toBeDisabled();
  });
});
