// ---------------------------------------------------------------------------
// Astra AI · RemoteTasks 单测（R4 / T2-62 · U-P2-41）
//
// 覆盖：
//   ① 工作区选择 → 项目/提交表单渲染；
//   ② 远程提交（固定 Agent 版本）→ 运行视图（状态 / Attempt / 日志 / 事件）；
//   ③ **显式 Apply** 命中**冻结路径** `POST /tasks/{id}/apply`（**非** `/diff/apply`）；
//   ④ **显式 Push** 命中 `POST /tasks/{id}/push`（独立权限）；
//   ⑤ 事件**断点续读**（`next_cursor`）；
//   ⑥ Diff 能力未装配 → **降级**（DEPENDENCY_MISSING）；
//   ⑦ `RequirePermission` 守卫（无 `git:apply` 时 Apply 按钮被拦）。
//
// 以 msw 打桩冻结 DTO（snake_case + 统一响应壳）；断言请求命中的**路径**。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { RemoteTasks } from "@/pages/RemoteTasks";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

const WORKSPACE = { id: "w1", tenant_id: "t1", name: "Demo Workspace" };
const PROJECT = {
  id: "p1",
  tenant_id: "t1",
  workspace_id: "w1",
  name: "proj",
  description: null,
  repo_url: "https://x/repo.git",
  default_branch: "main",
  settings: {},
};
const AGENT = { id: "a1", tenant_id: "t1", name: "Coder", status: "PUBLISHED" };
const AGENT_VERSION = { id: "av1", agent_id: "a1", version: "1", status: "PUBLISHED" };

/** 远程任务快照（`RemoteTaskViewResponse`）。 */
const REMOTE_VIEW = {
  task_id: "t1",
  type: "remote.agent.run",
  status: "SUCCESS",
  tenant_id: "t1",
  workspace_id: "w1",
  project_id: "p1",
  attempt_count: 1,
  checkout_ref: "wr_opaque",
  base_commit: "a".repeat(40),
  result_commit: "b".repeat(40),
  environment_digest: "d".repeat(64),
};

const ATTEMPT = {
  attempt: 1,
  status: "SUCCESS",
  checkout_ref: "wr_opaque",
  base_commit: "a".repeat(40),
  result_commit: "b".repeat(40),
  duration_ms: 1200,
};

const DIFF = {
  attempt: 1,
  checkout_ref: "wr_opaque",
  base_commit: "a".repeat(40),
  result_commit: "b".repeat(40),
  available: true,
  files: [{ path: "file.py", change_type: "modified", additions: 1, deletions: 0 }],
  truncated: false,
};

const LOG = { seq: 1, attempt: 1, level: "info", message: "boot" };
const EVENT_PAGE = {
  events: [{ seq: 1, type: "attempt.started", payload: {} }],
  next_cursor: "tev_bmV4dA",
};

/** 渲染 RemoteTasks（独立 QueryClient，禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <RemoteTasks />
    </QueryClientProvider>,
  );
}

/** 选工作区 → 选项目 → 选 Agent/版本 → 提交 → 展开运行视图。 */
async function submitRemoteTask() {
  // 等待 option 就绪后再 change（否则受控 select 的 value 落到「不存在选项」→ 空）。
  await screen.findByRole("option", { name: "Demo Workspace" });
  fireEvent.change(screen.getByTestId("remote-workspace-select"), {
    target: { value: "w1" },
  });

  await screen.findByRole("option", { name: "proj" });
  fireEvent.change(screen.getByTestId("remote-project-select"), {
    target: { value: "p1" },
  });

  fireEvent.change(screen.getByTestId("remote-agent-select"), { target: { value: "a1" } });

  await screen.findByRole("option", { name: "1" });
  fireEvent.change(screen.getByTestId("remote-agent-version-select"), {
    target: { value: "av1" },
  });

  fireEvent.click(screen.getByTestId("remote-submit-button"));
  await screen.findByTestId("remote-task-detail");
}

describe("RemoteTasks", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/workspaces", () => shell([WORKSPACE])),
      http.get("/api/v1/projects", () => shell([PROJECT])),
      http.get("/api/v1/agents", () => shell([AGENT])),
      http.get("/api/v1/agents/:agentId/versions", () => shell([AGENT_VERSION])),
      http.get("/api/v1/workflows", () => shell([])),
      http.post("/api/v1/tasks", () => shell({ task_id: "t1" }, 202)),
      http.get("/api/v1/tasks/:taskId", () => shell(REMOTE_VIEW)),
      http.get("/api/v1/tasks/:taskId/attempts", () => shell([ATTEMPT])),
      http.get("/api/v1/tasks/:taskId/logs", () => shell([LOG])),
      http.get("/api/v1/tasks/:taskId/events", () => shell(EVENT_PAGE)),
      http.get("/api/v1/tasks/:taskId/diff", () => shell(DIFF)),
      http.get("/api/v1/tasks/:taskId/artifacts", () => shell([])),
      http.post("/api/v1/tasks/:taskId/apply", () =>
        shell({
          task_id: "t1",
          target_ref: "main",
          base_commit: "a".repeat(40),
          result_commit: "b".repeat(40),
          applied_commit: "b".repeat(40),
          already_applied: false,
        }),
      ),
      http.post("/api/v1/tasks/:taskId/push", () =>
        shell({
          task_id: "t1",
          target_ref: "main",
          remote: "origin",
          ref: "refs/heads/main",
          pushed: true,
          already_up_to_date: false,
        }),
      ),
    );
  });

  it("提交远程任务后展示运行视图（状态 / Attempt / 日志 / 事件）", async () => {
    renderPage();
    await submitRemoteTask();

    expect(await screen.findByTestId("remote-task-status")).toHaveTextContent("SUCCESS");
    expect(await screen.findByTestId("remote-attempt-row-1")).toHaveTextContent("SUCCESS");
    expect(await screen.findByTestId("remote-log-1")).toHaveTextContent("boot");
    expect(await screen.findByTestId("remote-event-1")).toHaveTextContent("attempt.started");
    // 不透明 checkout_ref（**不含**宿主路径）。
    const checkoutRef = await screen.findByTestId("remote-task-checkout-ref");
    expect(checkoutRef).toHaveTextContent("wr_opaque");
    expect(checkoutRef.textContent).not.toContain("/");
  });

  it("显式 Apply 命中冻结路径 /tasks/{id}/apply 并反馈", async () => {
    let applyPath = "";
    server.use(
      http.post("/api/v1/tasks/:taskId/apply", ({ request }) => {
        applyPath = new URL(request.url).pathname;
        return shell({
          task_id: "t1",
          target_ref: "main",
          applied_commit: "b".repeat(40),
          already_applied: false,
        });
      }),
    );
    renderPage();
    await submitRemoteTask();

    fireEvent.click(screen.getByTestId("remote-apply-button"));
    expect(await screen.findByTestId("remote-change-feedback")).toHaveTextContent("已应用到 main");
    expect(applyPath).toBe("/api/v1/tasks/t1/apply");
  });

  it("显式 Push 命中 /tasks/{id}/push（独立权限）", async () => {
    let pushPath = "";
    server.use(
      http.post("/api/v1/tasks/:taskId/push", ({ request }) => {
        pushPath = new URL(request.url).pathname;
        return shell({
          task_id: "t1",
          target_ref: "main",
          remote: "origin",
          ref: "refs/heads/main",
          pushed: true,
          already_up_to_date: false,
        });
      }),
    );
    renderPage();
    await submitRemoteTask();

    fireEvent.click(screen.getByTestId("remote-push-button"));
    expect(await screen.findByTestId("remote-change-feedback")).toHaveTextContent(
      "已推送 refs/heads/main",
    );
    expect(pushPath).toBe("/api/v1/tasks/t1/push");
  });

  it("事件断点续读（续读使用 next_cursor）", async () => {
    const seenCursors: string[] = [];
    server.use(
      http.get("/api/v1/tasks/:taskId/events", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        seenCursors.push(cursor ?? "");
        if (cursor === "tev_bmV4dA") {
          return shell({
            events: [{ seq: 2, type: "attempt.finished", payload: {} }],
            next_cursor: "",
          });
        }
        return shell(EVENT_PAGE);
      }),
    );
    renderPage();
    await submitRemoteTask();

    fireEvent.click(await screen.findByTestId("remote-events-resume"));
    expect(await screen.findByTestId("remote-event-2")).toHaveTextContent("attempt.finished");
    expect(seenCursors).toContain("tev_bmV4dA");
  });

  it("Diff 能力未装配 → 降级（不伪造）", async () => {
    // 真实后端 `GET /tasks/{id}/diff` 以 **200 + available=false** 降级（非 503）。
    server.use(
      http.get("/api/v1/tasks/:taskId/diff", () =>
        shell({
          attempt: 1,
          checkout_ref: "wr_opaque",
          base_commit: null,
          result_commit: null,
          available: false,
          files: [],
          truncated: false,
        }),
      ),
    );
    renderPage();
    await submitRemoteTask();

    expect(await screen.findByTestId("remote-diff-degraded")).toBeInTheDocument();
  });

  it("RequirePermission 守卫：无 git:apply 时 Apply 按钮被拦", async () => {
    useAuthStore.setState({ permissions: ["task:submit", "project:create", "task:cancel"] });
    renderPage();
    await submitRemoteTask();

    expect(screen.getByText("缺少权限：git:apply")).toBeInTheDocument();
  });
});
