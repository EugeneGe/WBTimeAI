// ---------------------------------------------------------------------------
// Astra AI · Tasks 单测（W10 / T2-50 · U-P2-17/30）
//
// 覆盖：
//   ① 任务列表展示 + 类型/状态过滤；
//   ② 详情 + **执行历史**（`task_execution`，attempt/状态/耗时）；W10-E2；
//   ③ 取消（RUNNING 可取消；**终态禁用**）；
//   ④ Schedules 区：列表 + 手动触发；
//   ⑤ `can()` / `RequirePermission` 守卫（无 `task:cancel` 权限时取消按钮被拦）。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { Tasks } from "@/pages/Tasks";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

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

/** 渲染 Tasks（独立 QueryClient，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Tasks />
    </QueryClientProvider>,
  );
}

describe("Tasks", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/tasks", () => shell([TASK])),
      http.get("/api/v1/tasks/:taskId/executions", () => shell([EXEC])),
      http.get("/api/v1/tasks/:taskId", () => shell(TASK)),
      http.post("/api/v1/tasks/:taskId/cancel", () => shell({ ...TASK, status: "CANCELLED" })),
      http.get("/api/v1/schedules", () => shell([SCHEDULE])),
      http.post("/api/v1/schedules/:scheduleId/trigger", () =>
        shell({ schedule_id: "s1", task_id: "t9" }),
      ),
    );
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
});
