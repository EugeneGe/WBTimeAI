// ---------------------------------------------------------------------------
// WBTimeAI · RemoteTasks 单测（R4 / T2-62 · U-P2-41）
//
// 覆盖：
//   ① 工作区选择 → 项目/提交表单渲染；
//   ② 远程提交（固定 Agent 版本）→ 运行视图（状态 / Attempt / 日志 / 事件）；
//   ③ **显式 Apply** 命中**冻结路径** `POST /tasks/{id}/apply`（**非** `/diff/apply`）；
//   ④ **显式 Push** 命中 `POST /tasks/{id}/push`（独立权限）；
//   ⑤ 事件**断点续读**（`next_cursor`）；
//   ⑥ Diff 能力未装配 → **降级**（DEPENDENCY_MISSING）；
//   ⑦ `RequirePermission` 守卫（无 `git:apply` 时 Apply 按钮被拦）；
//   ⑧ 批 C-1 / M04-04：Artifact **逐行下载**（Blob → 临时 `<a download>`）；
//      批 E3：失败**可重试**（按钮不再永久禁用）+ ObjectURL 在 `finally` 释放；
//   ⑨ 批 C-1 / M04-04：**项目状态与克隆**卡（三项状态 / Clone 202 / refs 降级手填）；
//      批 E5：refs **成功但为空** 也降级手填。
//   ⑩ V0.4.6 B-24 重排：页头副标题 +「前往工作区」、运行视图五段 Tabs（常驻 + `hidden`）、
//      无工作区内联空态（可点 CTA、无聊天 chips）、「＋ 新建项目」弹窗。
//
// D-UI WS-P2：六处裸 `<select>` 已改 `ui/select`（radix）原语——交互由原生
// `change` 改为「点开触发器 → 点选 option」；jsdom 缺失的指针/滚动 API 在
// `beforeAll` 补齐（对齐 WS-F `ui/__tests__/select.test.tsx` 口径）。
// 以 msw 打桩冻结 DTO（snake_case + 统一响应壳）；断言请求命中的**路径**。
//
// 🔴 V0.4.6 缺陷 L-4 / 批次 B1：页面文案已全量 i18n 化（默认语言 `en`），故本文件在
//    `beforeEach` 显式切到 `zh-CN` 以保留既有中文断言（**断言文案不改**），
//    `afterEach` 复位 `en` 防跨文件语言污染；另有 1 条 en 态守卫用例。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { RemoteTasks } from "@/pages/RemoteTasks";
import { remoteTaskService } from "@/services/remoteTask";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** jsdom 未实现 ObjectURL API → 最小桩（计数供断言）。 */
const createObjectURLStub = vi.fn(() => "blob:mock-artifact");
const revokeObjectURLStub = vi.fn();
Object.defineProperty(URL, "createObjectURL", {
  value: createObjectURLStub,
  writable: true,
  configurable: true,
});
Object.defineProperty(URL, "revokeObjectURL", {
  value: revokeObjectURLStub,
  writable: true,
  configurable: true,
});

/** jsdom 缺失的指针/滚动 API 补齐（radix 开合与滚动定位所需）。 */
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

/** 远程 Project 状态（`ProjectStatusResponse`；**无**「最近同步时间」字段）。 */
const PROJECT_STATUS = {
  project_id: "p1",
  name: "proj",
  workspace_id: "w1",
  default_branch: "main",
  repo_configured: true,
  clone_task_id: "clone-9",
  refs_available: true,
};

/** Git 引用清单（`GitRefResponse`）。 */
const GIT_REFS = [
  { name: "refs/heads/main", commit: "a".repeat(40), kind: "branch" },
  { name: "v1.0.0", commit: "c".repeat(40), kind: "tag" },
];

/** 渲染 RemoteTasks（独立 QueryClient + Router 上下文，禁用重试）。 */
function renderPage(entry = "/remote-tasks") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <RemoteTasks />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * 打开 radix Select 并选中指定文案的选项。
 *
 * radix 触发器/选项在 **无指针事件序列** 下走 `click` 分支（`pointerTypeRef`
 * 默认 `"touch"`），故 `fireEvent.click` 即可开合与选中。
 */
async function chooseOption(triggerTestId: string, optionName: string) {
  const trigger = await screen.findByTestId(triggerTestId);
  fireEvent.click(trigger);
  const option = await screen.findByRole("option", { name: optionName });
  fireEvent.click(option);
}

/** 选工作区 → 选项目 → 选 Agent/版本 → 提交 → 展开运行视图。 */
async function submitRemoteTask() {
  await chooseOption("remote-workspace-select", "Demo Workspace");
  await chooseOption("remote-project-select", "proj");
  await chooseOption("remote-agent-select", "Coder");
  await chooseOption("remote-agent-version-select", "1");

  fireEvent.click(screen.getByTestId("remote-submit-button"));
  await screen.findByTestId("remote-task-detail");
}

describe("RemoteTasks", () => {
  beforeEach(() => {
    // 文案断言均为中文 → 用例内显式指定 `zh-CN`（默认语言是 `en`）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
    createObjectURLStub.mockClear();
    revokeObjectURLStub.mockClear();
    vi.restoreAllMocks();

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

  afterEach(() => {
    // 复位默认语言，避免污染其他测试文件（vitest 同进程复用 store）。
    useI18nStore.setState({ language: "en" });
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

  // --- 批 C-1 · M04-04：Artifact 逐行下载 ---------------------------------
  it("Artifact 逐行下载：Blob → ObjectURL → 临时 <a download>", async () => {
    server.use(
      http.get("/api/v1/tasks/:taskId/artifacts", () =>
        shell([{ name: "out.log", ref: "artifact:out.log", size: 5 }]),
      ),
    );
    const downloadSpy = vi
      .spyOn(remoteTaskService, "downloadArtifact")
      .mockResolvedValue(new Blob(["hello"], { type: "text/plain" }));
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation((): void => undefined);

    renderPage();
    await submitRemoteTask();

    const button = await screen.findByTestId("remote-artifact-download-out.log");
    fireEvent.click(button);

    await waitFor(() => expect(downloadSpy).toHaveBeenCalledTimes(1));
    // 逐项重新鉴权：携带当前任务与 attempt（未选 Attempt → null，服务层转 undefined）。
    expect(downloadSpy).toHaveBeenCalledWith("t1", "out.log", { attempt: null });
    await waitFor(() => expect(revokeObjectURLStub).toHaveBeenCalledWith("blob:mock-artifact"));
    expect(createObjectURLStub).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    // 成功后整行恢复（无「下载失败」文案、按钮可再次点击）。
    expect(screen.queryByTestId("remote-artifact-download-error-out.log")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("remote-artifact-download-out.log")).toBeEnabled(),
    );
  });

  it("Artifact 下载失败：行内「下载失败」+ 按钮**可重试**（批 E3）", async () => {
    server.use(
      http.get("/api/v1/tasks/:taskId/artifacts", () =>
        shell([{ name: "broken.bin", ref: "artifact:broken.bin" }]),
      ),
    );
    const downloadSpy = vi
      .spyOn(remoteTaskService, "downloadArtifact")
      .mockRejectedValue(new Error("boom"));

    renderPage();
    await submitRemoteTask();

    fireEvent.click(await screen.findByTestId("remote-artifact-download-broken.bin"));

    const hint = await screen.findByTestId("remote-artifact-download-error-broken.bin");
    expect(hint).toHaveTextContent("下载失败");
    // 不弹全局错误（页面既有反馈区保持静默）。
    expect(screen.queryByTestId("remote-change-feedback")).not.toBeInTheDocument();

    // 批 E3：失败后按钮**不再永久禁用**，可再次点击并真正重发请求。
    const button = screen.getByTestId("remote-artifact-download-broken.bin");
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(downloadSpy).toHaveBeenCalledTimes(2));
    expect(
      await screen.findByTestId("remote-artifact-download-error-broken.bin"),
    ).toHaveTextContent("下载失败");
  });

  it("Artifact 下载中 DOM 抛错也不泄漏 ObjectURL（批 E3：finally revoke）", async () => {
    server.use(
      http.get("/api/v1/tasks/:taskId/artifacts", () =>
        shell([{ name: "leak.bin", ref: "artifact:leak.bin" }]),
      ),
    );
    vi.spyOn(remoteTaskService, "downloadArtifact").mockResolvedValue(
      new Blob(["x"], { type: "application/octet-stream" }),
    );
    // `createObjectURL` 之后的 DOM 语句抛错 → 仍必须走到 `finally` 释放 URL。
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation((): void => {
      throw new Error("dom boom");
    });

    renderPage();
    await submitRemoteTask();

    fireEvent.click(await screen.findByTestId("remote-artifact-download-leak.bin"));

    await waitFor(() => expect(revokeObjectURLStub).toHaveBeenCalledWith("blob:mock-artifact"));
    expect(createObjectURLStub).toHaveBeenCalledTimes(1);
    // 抛错按失败处理（行内文案），且按钮可重试。
    expect(await screen.findByTestId("remote-artifact-download-error-leak.bin")).toHaveTextContent(
      "下载失败",
    );
    expect(screen.getByTestId("remote-artifact-download-leak.bin")).toBeEnabled();
  });

  // --- 批 C-1 · M04-04：项目状态与克隆 ------------------------------------
  it("项目状态卡：空态 → 三项状态 → refs 下拉 → Clone 202 反馈", async () => {
    let clonePath = "";
    let cloneBody: unknown = null;
    server.use(
      http.get("/api/v1/projects/:projectId/status", () => shell(PROJECT_STATUS)),
      http.get("/api/v1/projects/:projectId/git/refs", () => shell(GIT_REFS)),
      http.post("/api/v1/projects/:projectId/clone", async ({ request }) => {
        clonePath = new URL(request.url).pathname;
        cloneBody = await request.json();
        return shell({ task_id: "clone-task-1" }, 202);
      }),
    );

    renderPage();
    await chooseOption("remote-workspace-select", "Demo Workspace");

    expect(await screen.findByTestId("remote-project-status-empty")).toHaveTextContent(
      "选择项目后查看克隆状态",
    );

    await chooseOption("remote-project-status-select", "proj");

    await waitFor(() =>
      expect(screen.getByTestId("remote-project-repo-state")).toHaveTextContent("已克隆"),
    );
    expect(screen.getByTestId("remote-project-default-branch")).toHaveTextContent("main");
    // 设计稿「最近同步」→ 实际以 `clone_task_id`（**最近克隆任务**）呈现，不自造字段。
    expect(screen.getByTestId("remote-project-clone-task")).toHaveTextContent("clone-9");

    await chooseOption("remote-project-ref-select", "v1.0.0");
    fireEvent.click(screen.getByTestId("remote-project-clone-button"));

    expect(await screen.findByTestId("remote-project-clone-feedback")).toHaveTextContent(
      "已提交克隆，进度见任务中心",
    );
    expect(clonePath).toBe("/api/v1/projects/p1/clone");
    expect(cloneBody).toEqual({ base_ref: "v1.0.0" });
  });

  it("refs 未装配（refs_available=false + 503）→ 降级手填，手填值进入 base_ref", async () => {
    let cloneBody: unknown = null;
    server.use(
      http.get("/api/v1/projects/:projectId/status", () =>
        shell({
          ...PROJECT_STATUS,
          repo_configured: false,
          default_branch: null,
          clone_task_id: null,
          refs_available: false,
        }),
      ),
      http.get("/api/v1/projects/:projectId/git/refs", () => shell(null, 503)),
      http.post("/api/v1/projects/:projectId/clone", async ({ request }) => {
        cloneBody = await request.json();
        return shell({ task_id: "clone-task-2" }, 202);
      }),
    );

    renderPage();
    await chooseOption("remote-workspace-select", "Demo Workspace");
    await chooseOption("remote-project-status-select", "proj");

    const input = await screen.findByTestId("remote-project-ref-input");
    expect(input).toHaveAttribute("placeholder", "refs 未装配，手填分支/标签");
    await waitFor(() =>
      expect(screen.getByTestId("remote-project-repo-state")).toHaveTextContent("未克隆"),
    );
    expect(screen.getByTestId("remote-project-clone-task")).toHaveTextContent("—");

    fireEvent.change(input, { target: { value: "release/1.0" } });
    fireEvent.click(screen.getByTestId("remote-project-clone-button"));

    await waitFor(() => expect(cloneBody).toEqual({ base_ref: "release/1.0" }));
  });

  it("refs 请求成功但列表为空 → 仍降级手填（批 E5）", async () => {
    let cloneBody: unknown = null;
    server.use(
      http.get("/api/v1/projects/:projectId/status", () => shell(PROJECT_STATUS)),
      // 能力在（`refs_available: true`），但仓库无任何分支/标签 → 下拉零选项。
      http.get("/api/v1/projects/:projectId/git/refs", () => shell([])),
      http.post("/api/v1/projects/:projectId/clone", async ({ request }) => {
        cloneBody = await request.json();
        return shell({ task_id: "clone-task-3" }, 202);
      }),
    );

    renderPage();
    await chooseOption("remote-workspace-select", "Demo Workspace");
    await chooseOption("remote-project-status-select", "proj");

    const input = await screen.findByTestId("remote-project-ref-input");
    expect(input).toHaveAttribute("placeholder", "refs 未装配，手填分支/标签");
    // 下拉不再渲染（零选项时用户无法选择）。
    expect(screen.queryByTestId("remote-project-ref-select")).toBeNull();

    fireEvent.change(input, { target: { value: "hotfix/1" } });
    fireEvent.click(screen.getByTestId("remote-project-clone-button"));

    await waitFor(() => expect(cloneBody).toEqual({ base_ref: "hotfix/1" }));
  });

  // --- V0.4.6 · B-24：页头 / 上下文条 / 运行视图 Tabs / 空态 -----------------
  it("页头：副标题流程指引 +「前往工作区」链接", async () => {
    renderPage();

    expect(await screen.findByTestId("remote-subtitle")).toHaveTextContent(
      "选择工作区 → 提交任务 → 审阅 Diff / 产物 → Apply 或 Push",
    );
    expect(screen.getByTestId("remote-goto-workspace")).toHaveAttribute("href", "/workspace");
  });

  it("运行视图五段 Tabs：全部挂载，切「尝试」隐藏状态面板", async () => {
    renderPage();
    await submitRemoteTask();

    for (const key of ["status", "attempts", "logs", "events", "changes"]) {
      expect(screen.getByTestId(`remote-tab-${key}`)).toBeInTheDocument();
      expect(screen.getByTestId(`remote-panel-${key}`)).toBeInTheDocument();
    }

    // 默认「状态」：状态面板可见、其余 `hidden`（但仍在 DOM 内）。
    expect(screen.getByTestId("remote-panel-status")).not.toHaveAttribute("hidden");
    expect(screen.getByTestId("remote-panel-attempts")).toHaveAttribute("hidden");

    fireEvent.click(screen.getByTestId("remote-tab-attempts"));

    expect(screen.getByTestId("remote-panel-status")).toHaveAttribute("hidden");
    expect(screen.getByTestId("remote-panel-attempts")).not.toHaveAttribute("hidden");
    // 面板常驻：切走后面板内容仍可取到（既有用例依赖）。
    expect(screen.getByTestId("remote-attempt-row-1")).toBeInTheDocument();
  });

  it("无工作区：内联空态可点 CTA + 无聊天 chips", async () => {
    server.use(http.get("/api/v1/workspaces", () => shell([])));
    renderPage();

    expect(await screen.findByTestId("remote-workspaces-empty")).toHaveTextContent("尚无工作区");
    expect(screen.getByTestId("remote-workspaces-empty-cta")).toHaveAttribute("href", "/workspace");
    expect(screen.getByTestId("remote-workspaces-empty-refresh")).toBeInTheDocument();
    // B-24：空态不再借用聊天招呼语组件的 chips。
    expect(screen.queryByTestId(/^empty-state-chip-/)).toBeNull();
  });

  it("「＋ 新建项目」打开弹窗（三输入保留）并创建成功", async () => {
    server.use(
      http.post("/api/v1/projects", () => shell({ ...PROJECT, id: "p2", name: "newproj" }, 201)),
    );
    renderPage();
    await chooseOption("remote-workspace-select", "Demo Workspace");

    fireEvent.click(screen.getByTestId("remote-new-project-open"));

    const nameInput = await screen.findByTestId("remote-new-project-name");
    expect(nameInput).toBeInTheDocument();
    expect(screen.getByTestId("remote-new-project-repo")).toBeInTheDocument();
    expect(screen.getByTestId("remote-new-project-branch")).toBeInTheDocument();

    fireEvent.change(nameInput, { target: { value: "newproj" } });
    fireEvent.click(screen.getByTestId("remote-create-project-button"));

    expect(await screen.findByTestId("remote-project-feedback")).toHaveTextContent(
      "已创建项目 newproj",
    );
  });

  // --- V0.4.6 · B-24 收尾：URL 上下文消费 + 上下文条权限守卫 ---------------
  it("URL 上下文 ?workspace=&project=：进入即预选工作区与项目", async () => {
    renderPage("/remote-tasks?workspace=w1&project=p1");

    await waitFor(() =>
      expect(screen.getByTestId("remote-workspace-select")).toHaveTextContent("Demo Workspace"),
    );
    // 提交卡的项目下拉命中 `?project=` 指向的项目（项目列表就绪后预选）。
    await waitFor(() =>
      expect(screen.getByTestId("remote-project-select")).toHaveTextContent("proj"),
    );
  });

  it("URL 上下文缺失：不预选（保持未选工作区，项目卡不渲染）", async () => {
    renderPage("/remote-tasks");

    expect(await screen.findByTestId("remote-workspace-hint")).toBeInTheDocument();
    expect(screen.getByTestId("remote-workspace-select")).toHaveTextContent("选择工作区");
    expect(screen.queryByTestId("remote-project-select")).toBeNull();
  });

  it("无 project:create 权限：上下文条不渲染「＋ 新建项目」", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage("/remote-tasks?workspace=w1");

    await waitFor(() =>
      expect(screen.getByTestId("remote-workspace-select")).toHaveTextContent("Demo Workspace"),
    );
    expect(screen.queryByTestId("remote-new-project-open")).toBeNull();
    // 🔴 反向控制组：`queryByTestId("remote-new-project-open")` 对「守卫走了
    // `fallback={null}` 什么都没渲染」与「渲染了 p-8 默认占位块」**同为 null**
    // （两条断言的 `toBeNull()` 无法区分二者）。故显式排除 `project:create` 的默认占位：
    // 修复前 `fallback ?? <PermissionDenied/>` 会把 `null` 吞掉并渲染占位 → 本断言红。
    // 注：本页 `task:submit` / `git:apply` 等守卫**无** fallback，其默认占位属预期，
    // 因此这里按 `data-permission-code` 精确过滤，不断言「全页无占位」。
    const deniedPlaceholders = screen.queryAllByTestId("permission-denied");
    expect(
      deniedPlaceholders.some((el) => el.getAttribute("data-permission-code") === "project:create"),
    ).toBe(false);
    // 其他上下文条入口不受影响。
    expect(screen.getByTestId("remote-project-status-anchor")).toBeInTheDocument();
  });

  // V0.4.6 缺陷 L-4 / 批次 B1：默认语言 en 下不得露中文（页头 / 副标题 / 空态 / 按钮）。
  it("i18n：切到 en → 页头与副标题为英文，不残留中文", async () => {
    useI18nStore.setState({ language: "en" });
    renderPage();

    expect(await screen.findByTestId("remote-workspace-hint")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Remote Workbench");
    expect(screen.getByTestId("remote-subtitle")).toHaveTextContent("Pick a workspace");
    expect(screen.getByTestId("remote-goto-workspace")).toHaveTextContent("Go to workspace");

    // 中文文案均已切到 en 资源。
    expect(screen.queryByText("远程工作台")).toBeNull();
    expect(screen.queryByText("前往工作区")).toBeNull();
  });
});
