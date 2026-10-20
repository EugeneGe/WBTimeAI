// ---------------------------------------------------------------------------
// WBTimeAI · Tasks 单测（W10 / T2-50 · U-P2-17/30；M04-03 列表补列 + 调度启用列；
// **B-20 UI 优化 + 调度 CRUD**）
//
// 覆盖：
//   ① 任务列表展示 + 类型/状态过滤；
//   ② 详情 + **执行历史**（`task_execution`，attempt/状态/耗时）；W10-E2；
//   ③ 取消（RUNNING 可取消；**终态禁用**）；
//   ④ Schedules 区：列表 + 手动触发；
//   ⑤ `can()` / `RequirePermission` 守卫（无 `task:cancel` 权限时取消按钮被拦）；
//   ⑥ **M04-03**：执行模式列（真实值 INLINE/QUEUED）+ 来源徽标（按 `project_id` 判定）
//      + 远程行「审阅」入口；
//   ⑦ **M04-03 / B-20**：调度「启用」开关（`role="switch"`；`PUT /schedules/{id}` 只传
//      `{enabled}`；失败行内提示）；
//   ⑧ **B-20**：页头副标题计数、内联空态（**不**复用 `EmptyState` chips）、
//      新建 / 编辑 / 删除调度的请求契约、payload 非法 JSON 拦截。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// 注：页面使用 `useNavigate`（远程行「审阅」/ 空态 CTA），故统一包裹 `MemoryRouter`。
//
// 🔴 V0.4.6 缺陷 L-4 / 批次 B1：页面文案已全量 i18n 化（默认语言 `en`），故本文件在
//    `beforeEach` 显式切到 `zh-CN` 以保留既有中文断言（**断言文案不改**），
//    `afterEach` 复位 `en` 防跨文件语言污染；另有 1 条 en 态守卫用例。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { Tasks } from "@/pages/Tasks";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

// Radix Select / Dialog 依赖的 jsdom 缺失 API（指针捕获 / 滚动 / ResizeObserver）。
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

/** 任务夹具（`TaskResponse`，RUNNING 可取消）。 */
const TASK = {
  id: "t1",
  tenant_id: "t1",
  workspace_id: "w1",
  type: "agent.run",
  status: "RUNNING",
  priority: 0,
  execution_mode: "INLINE",
  payload: { agent_id: "a1" },
  result: null,
  error: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
};

/** 执行记录夹具（`TaskExecutionResponse`）。 */
const EXEC = {
  id: "e1",
  task_id: "t1",
  attempt: 1,
  worker_id: "worker-1",
  status: "RUNNING",
  started_at: "2026-10-13T00:00:00Z",
  finished_at: null,
  duration_ms: null,
  error: null,
};

/** 调度夹具（`ScheduleResponse`）。 */
const SCHEDULE = {
  id: "s1",
  tenant_id: "t1",
  organization_id: null,
  workspace_id: null,
  name: "Nightly",
  target_type: "agent",
  target_id: "a1",
  trigger: "manual",
  cron: null,
  event_type: null,
  payload: {},
  enabled: true,
  last_run_at: null,
  next_run_at: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
};

/** 渲染 Tasks（独立 QueryClient，禁用重试；Router 上下文供 `useNavigate`）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/tasks"]}>
        <Tasks />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * 选择 Radix Select 的某一项（打开 → 按名称点击 option）。
 *
 * Radix `SelectItem` 的 `onClick` 在「非 mouse 指针」下直接用 `handleSelect`，
 * 因此 `fireEvent.click(option)` 可完成选择（无需模拟 pointerup）。
 */
async function selectOption(testId: string, optionName: string): Promise<void> {
  const trigger = screen.getByTestId(testId);
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: optionName }));
}

describe("Tasks", () => {
  beforeEach(() => {
    // 文案断言均为中文 → 用例内显式指定 `zh-CN`（默认语言是 `en`）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/tasks", () => shell([TASK])),
      http.get("/api/v1/tasks/:taskId/executions", () => shell([EXEC])),
      http.get("/api/v1/tasks/:taskId", () => shell(TASK)),
      http.post("/api/v1/tasks/:taskId/cancel", () => shell({ ...TASK, status: "CANCELLED" })),
      http.get("/api/v1/schedules", () => shell([SCHEDULE])),
      http.post("/api/v1/schedules", () => shell({ ...SCHEDULE, id: "s2" }, 201)),
      http.post("/api/v1/schedules/:scheduleId/trigger", () =>
        shell({ schedule_id: "s1", task_id: "t9" }),
      ),
      http.put("/api/v1/schedules/:scheduleId", () => shell({ ...SCHEDULE, enabled: false })),
      http.delete("/api/v1/schedules/:scheduleId", () => new HttpResponse(null, { status: 204 })),
    );
  });

  afterEach(() => {
    // 复位默认语言，避免污染其他测试文件（vitest 同进程复用 store）。
    useI18nStore.setState({ language: "en" });
  });

  it("展示任务列表、详情与执行历史", async () => {
    renderPage();

    expect(await screen.findByTestId("task-row-t1")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("task-select-t1"));
    expect(await screen.findByTestId("task-detail")).toBeInTheDocument();
    expect(screen.getByTestId("task-status")).toHaveTextContent("RUNNING");

    expect(await screen.findByTestId("execution-row-1")).toHaveTextContent("RUNNING");
  });

  it("取消任务（RUNNING）→ 反馈", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("task-select-t1"));
    const cancelButton = await screen.findByTestId("task-cancel-button");
    expect(cancelButton).toBeEnabled();

    fireEvent.click(cancelButton);
    expect(await screen.findByTestId("task-detail-feedback")).toHaveTextContent(
      "已请求取消（CANCELLED）",
    );
  });

  it("终态任务的取消按钮被禁用", async () => {
    server.use(http.get("/api/v1/tasks/:taskId", () => shell({ ...TASK, status: "SUCCESS" })));
    renderPage();

    fireEvent.click(await screen.findByTestId("task-select-t1"));
    expect(await screen.findByTestId("task-cancel-button")).toBeDisabled();
  });

  it("详情面板「收起」清空选中态", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("task-select-t1"));
    expect(await screen.findByTestId("task-detail")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("task-detail-collapse"));
    await waitFor(() => expect(screen.queryByTestId("task-detail")).toBeNull());
  });

  it("Schedules 区展示调度并可手动触发", async () => {
    renderPage();

    expect(await screen.findByTestId("schedule-row-s1")).toHaveTextContent("Nightly");

    fireEvent.click(screen.getByTestId("schedule-trigger-s1"));
    expect(await screen.findByTestId("tasks-feedback")).toHaveTextContent("已触发调度（task t9）");
  });

  it("can() 守卫：无 task:cancel 权限时取消按钮被拦", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();

    fireEvent.click(await screen.findByTestId("task-select-t1"));
    expect(await screen.findByText("缺少权限：task:cancel")).toBeInTheDocument();
  });

  it("M04-03：来源徽标按 project_id 判定（顶层字段 / payload 两种口径）+ 远程行「审阅」入口", async () => {
    server.use(
      http.get("/api/v1/tasks", () =>
        shell([
          // ① 按项目过滤口径（`_to_remote_view_as_task`）：顶层 `project_id` 有值。
          { ...TASK, id: "t1", project_id: "p1", execution_mode: "QUEUED" },
          // ② 全量列表口径（`_to_task_response`）：只有 `payload.project_id`。
          { ...TASK, id: "t2", execution_mode: "INLINE", payload: { project_id: "p1" } },
          // ③ 本地任务：两处都没有 project_id。
          { ...TASK, id: "t3", execution_mode: "INLINE", payload: { agent_id: "a1" } },
        ]),
      ),
    );
    renderPage();

    // 执行模式列按**真实值**渲染（INLINE / QUEUED），不映射为「本地 / 远程」。
    expect(await screen.findByTestId("task-execution-mode-t1")).toHaveTextContent("QUEUED");
    expect(screen.getByTestId("task-execution-mode-t2")).toHaveTextContent("INLINE");
    expect(screen.getByTestId("task-execution-mode-t3")).toHaveTextContent("INLINE");

    // 来源徽标：两种远程口径都判为「远程」，本地任务为「本地」。
    expect(screen.getByTestId("task-source-t1")).toHaveTextContent("远程");
    expect(screen.getByTestId("task-source-t2")).toHaveTextContent("远程");
    expect(screen.getByTestId("task-source-t3")).toHaveTextContent("本地");

    // 表头列序（B-20 补「任务 / 创建时间」两列）：任务 → 类型 → 执行模式 → 状态 → 优先级
    // → 创建时间 → 操作。
    const taskHeaders = screen
      .getAllByRole("columnheader")
      .slice(0, 7)
      .map((cell) => cell.textContent);
    expect(taskHeaders).toEqual(["任务", "类型", "执行模式", "状态", "优先级", "创建时间", "操作"]);

    // 远程行「审阅」在「详情」前；本地行**无**「审阅」，只有「详情」。
    const review = screen.getByTestId("task-review-t1");
    const detail = screen.getByTestId("task-select-t1");
    expect(review.compareDocumentPosition(detail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId("task-review-t2")).toBeInTheDocument();
    expect(screen.queryByTestId("task-review-t3")).toBeNull();
    expect(screen.getByTestId("task-select-t3")).toBeInTheDocument();
  });

  it("B-20：页头副标题展示任务 / 调度计数", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getByTestId("tasks-subtitle")).toHaveTextContent(
        "任务与调度的统一控制台 · 共 1 个任务 · 1 个调度（1 启用）",
      ),
    );
  });

  it("B-20：空任务 + 空调度 → 两个内联空态（不复用 EmptyState chips）", async () => {
    server.use(
      http.get("/api/v1/tasks", () => shell([])),
      http.get("/api/v1/schedules", () => shell([])),
    );
    renderPage();

    expect(await screen.findByTestId("tasks-empty")).toHaveTextContent("暂无任务");
    expect(screen.getByTestId("tasks-empty-cta")).toBeInTheDocument();

    expect(await screen.findByTestId("schedules-empty")).toHaveTextContent("暂无调度");
    expect(screen.getByTestId("schedule-create-open-empty")).toBeInTheDocument();

    // 不再复用聊天空态：无品牌标 / 无场景 chips。
    expect(screen.queryByTestId("empty-state")).toBeNull();
    expect(screen.queryAllByTestId(/^empty-state-chip-/)).toHaveLength(0);
  });

  it("M04-03 / B-20：调度「启用」开关（role=switch）→ PUT 只传 {enabled}", async () => {
    let putBody: unknown = null;
    server.use(
      http.put("/api/v1/schedules/:scheduleId", async ({ request }) => {
        putBody = await request.json();
        return shell({ ...SCHEDULE, enabled: false });
      }),
    );
    renderPage();

    const toggle = await screen.findByTestId("schedule-toggle-s1");
    expect(toggle).toHaveAttribute("role", "switch");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveAttribute("aria-label", "停用");

    const scheduleHeaders = within(screen.getByTestId("schedules-list"))
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(scheduleHeaders).toEqual(["名称", "目标", "触发", "启用", "上次 · 下次", "操作"]);

    fireEvent.click(toggle);
    await waitFor(() => expect(putBody).toEqual({ enabled: false }));
  });

  it("M04-03：启用开关失败 → 仅本行「切换失败」提示", async () => {
    server.use(
      http.get("/api/v1/schedules", () =>
        shell([SCHEDULE, { ...SCHEDULE, id: "s2", name: "Other" }]),
      ),
      http.put("/api/v1/schedules/:scheduleId", () =>
        HttpResponse.json({ code: "INTERNAL_ERROR", message: "boom", data: {} }, { status: 500 }),
      ),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("schedule-toggle-s1"));
    expect(await screen.findByTestId("schedule-toggle-error-s1")).toHaveTextContent("切换失败");
    expect(screen.queryByTestId("schedule-toggle-error-s2")).toBeNull();
  });

  it("B-20：新建调度 → POST /schedules（含 target_type / target_id / cron / enabled）", async () => {
    let postBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/schedules", async ({ request }) => {
        postBody = (await request.json()) as Record<string, unknown>;
        return shell({ ...SCHEDULE, id: "s2", name: "每日巡检" }, 201);
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("schedule-create-open"));
    expect(await screen.findByTestId("schedule-dialog")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("schedule-dialog-name"), {
      target: { value: "每日巡检" },
    });
    fireEvent.change(screen.getByTestId("schedule-dialog-target-id"), {
      target: { value: "a1" },
    });
    await selectOption("schedule-dialog-trigger", "cron");
    fireEvent.change(await screen.findByTestId("schedule-dialog-cron"), {
      target: { value: "0 2 * * *" },
    });
    fireEvent.click(screen.getByTestId("schedule-dialog-submit"));

    await waitFor(() =>
      expect(postBody).toEqual({
        name: "每日巡检",
        target_type: "agent",
        target_id: "a1",
        trigger: "cron",
        cron: "0 2 * * *",
        event_type: null,
        payload: {},
        enabled: true,
      }),
    );
    expect(await screen.findByTestId("tasks-feedback")).toHaveTextContent("已创建调度");
    await waitFor(() => expect(screen.queryByTestId("schedule-dialog")).toBeNull());
  });

  it("B-20：编辑调度 → PUT 预填名称且**不含** target_id（创建后不可改）", async () => {
    let putBody: Record<string, unknown> | null = null;
    server.use(
      http.put("/api/v1/schedules/:scheduleId", async ({ request }) => {
        putBody = (await request.json()) as Record<string, unknown>;
        return shell({ ...SCHEDULE, name: "Nightly v2" });
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("schedule-edit-s1"));

    const nameInput = await screen.findByTestId("schedule-dialog-name");
    expect(nameInput).toHaveValue("Nightly");
    // 目标两字段在编辑态置灰（`UpdateScheduleRequest` 不支持改目标）。
    expect(screen.getByTestId("schedule-dialog-target-id")).toBeDisabled();

    fireEvent.change(nameInput, { target: { value: "Nightly v2" } });
    fireEvent.click(screen.getByTestId("schedule-dialog-submit"));

    await waitFor(() =>
      expect(putBody).toEqual({
        name: "Nightly v2",
        trigger: "manual",
        cron: null,
        event_type: null,
        payload: {},
        enabled: true,
      }),
    );
    expect(putBody).not.toHaveProperty("target_id");
    expect(putBody).not.toHaveProperty("target_type");
    expect(await screen.findByTestId("tasks-feedback")).toHaveTextContent("已更新调度");
  });

  it("B-20：删除调度 → 二次确认后调用 DELETE", async () => {
    let deleted = false;
    server.use(
      http.delete("/api/v1/schedules/:scheduleId", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("schedule-delete-s1"));
    expect(await screen.findByTestId("schedule-delete-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("schedule-delete-name")).toHaveTextContent("Nightly");

    fireEvent.click(screen.getByTestId("schedule-delete-confirm"));

    await waitFor(() => expect(deleted).toBe(true));
    expect(await screen.findByTestId("tasks-feedback")).toHaveTextContent("已删除调度");
  });

  it("B-20：payload 非法 JSON → 行内报错且不发请求", async () => {
    let postCount = 0;
    server.use(
      http.post("/api/v1/schedules", () => {
        postCount += 1;
        return shell(SCHEDULE, 201);
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("schedule-create-open"));
    fireEvent.change(await screen.findByTestId("schedule-dialog-name"), {
      target: { value: "坏 payload" },
    });
    fireEvent.change(screen.getByTestId("schedule-dialog-target-id"), {
      target: { value: "a1" },
    });
    fireEvent.change(screen.getByTestId("schedule-dialog-payload"), {
      target: { value: "{oops" },
    });
    fireEvent.click(screen.getByTestId("schedule-dialog-submit"));

    expect(await screen.findByTestId("schedule-dialog-error")).toBeInTheDocument();
    expect(postCount).toBe(0);
    // 弹窗不关闭，便于用户修正。
    expect(screen.getByTestId("schedule-dialog")).toBeInTheDocument();
  });

  // V0.4.6 缺陷 L-4 / 批次 B1：默认语言 en 下不得露中文（页头 / 表头 / 过滤器 / 按钮）。
  it("i18n：切到 en → 页头与任务表头为英文，不残留中文", async () => {
    useI18nStore.setState({ language: "en" });
    renderPage();

    expect(await screen.findByTestId("task-row-t1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Task Center");

    const headers = screen
      .getAllByRole("columnheader")
      .slice(0, 7)
      .map((cell) => cell.textContent);
    expect(headers).toEqual([
      "Task",
      "Type",
      "Execution mode",
      "Status",
      "Priority",
      "Created",
      "Actions",
    ]);
    // 关键中文文案已不在 en 下出现；来源徽标走英文取值。
    expect(screen.queryByText("任务中心")).toBeNull();
    expect(screen.queryByText("全部类型")).toBeNull();
    expect(screen.getByTestId("task-source-t1")).toHaveTextContent("Local");
  });
});
