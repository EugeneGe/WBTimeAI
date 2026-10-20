// ---------------------------------------------------------------------------
// WBTimeAI · WorkflowDesigner 单测（W6 / T2-35 · U-P2-30 / Q-76；B-21 增补）
//
// 覆盖：
//   ① 加节点 → 连线 → 保存 = 新 workflow_version（不可变）；
//   ② 8 类节点面板齐备（左列纵向面板，testid 不变）；
//   ③ 发布载荷含既有 + 新增节点与连线，版本列表追加新版本；
//   ④ 工作流空列表 → 内联空态，**不再渲染聊天示例 chips**（B-21 回归）；
//   ⑤ 重命名 → `PUT /workflows/{id}` 只传 `{ name }`；
//   ⑥ 删除 → `DELETE /workflows/{id}`；
//   ⑦ 版本「载入」 → 画布回灌该版本 definition（保存仍生成新版本）。
//
// React Flow 以轻量 mock 替代（jsdom 无真实布局），交互经面板 + 连接按钮触发。
//
// 🔴 V0.4.6 缺陷 L-4 / 批次 B2：页面文案已全量 i18n 化（默认语言 `en`），故本文件在
//    `beforeEach` 显式切到 `zh-CN` 以保留既有中文断言（**断言文案不改**），
//    `afterEach` 复位 `en` 防跨文件语言污染；另有 1 条 en 态守卫用例。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowDesigner } from "@/pages/studio/WorkflowDesigner";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";
import {
  WORKFLOW,
  WORKFLOW_RUN,
  WORKFLOW_RUN_DETAIL,
  WORKFLOW_RUN_DIGEST,
  WORKFLOW_VERSION,
  shell,
} from "@/test/msw-handlers";
import { server } from "@/test/setup";

// --- jsdom 补丁：radix（dropdown-menu / dialog）与浮层定位所需最小实现 ---------
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe(): void {
      void 0;
    }
    unobserve(): void {
      void 0;
    }
    disconnect(): void {
      void 0;
    }
  } as unknown as typeof ResizeObserver;
}
if (typeof window.PointerEvent === "undefined") {
  class PointerEventPolyfill extends MouseEvent {
    pointerType: string;
    pointerId: number;

    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params);
      this.pointerType = params.pointerType ?? "";
      this.pointerId = params.pointerId ?? 0;
    }
  }
  window.PointerEvent = PointerEventPolyfill as unknown as typeof PointerEvent;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = (): void => {
    void 0;
  };
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = (): boolean => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = (): void => {
    void 0;
  };
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = (): void => {
    void 0;
  };
}

// React Flow v12 轻量替身：渲染节点标签 + 提供一个受控的连接按钮。
vi.mock("@xyflow/react", () => {
  interface MockNode {
    id: string;
    data?: { label?: string };
  }
  interface MockConnection {
    source: string;
    target: string;
  }
  return {
    ReactFlow: ({
      nodes,
      onConnect,
    }: {
      nodes?: MockNode[];
      onConnect?: (connection: MockConnection) => void;
    }) => {
      const list = nodes ?? [];
      return (
        <div data-testid="rf">
          {list.map((node) => (
            <div key={node.id} data-testid={`rf-node-${node.id}`}>
              {node.data?.label}
            </div>
          ))}
          <button
            type="button"
            data-testid="rf-connect"
            onClick={() => {
              if (list.length >= 2) {
                onConnect?.({ source: list[0].id, target: list[1].id });
              }
            }}
          >
            connect
          </button>
        </div>
      );
    },
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
    addEdge: (...args: unknown[]) => [...(args[1] as unknown[]), args[0]],
    applyNodeChanges: (...args: unknown[]) => args[1],
    applyEdgeChanges: (...args: unknown[]) => args[1],
  };
});

/** 渲染 Designer（带独立 QueryClient；命中 msw 契约 handler）。 */
function renderDesigner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <WorkflowDesigner />
    </QueryClientProvider>,
  );
}

/** 打开 radix DropdownMenu（触发器响应 pointerdown）。 */
function openDropdown(trigger: HTMLElement): void {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
}

describe("WorkflowDesigner", () => {
  beforeEach(() => {
    // 文案断言均为中文 → 用例内显式指定 `zh-CN`（默认语言是 `en`）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  afterEach(() => {
    // 复位默认语言，避免污染其他测试文件（vitest 同进程复用 store）。
    useI18nStore.setState({ language: "en" });
  });

  it("加节点 → 连线 → 保存 = 新版本（不可变）", async () => {
    renderDesigner();

    // 选择既有 Workflow → 载入最新版本快照（n1 / n2）。
    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    expect(screen.getByTestId("rf-node-n2")).toBeInTheDocument();

    // 节点面板：添加一个 TOOL 节点（n3）。
    fireEvent.click(screen.getByTestId("add-node-TOOL"));
    await screen.findByTestId("rf-node-n3");

    // 连线（↔ workflow_edge）。
    fireEvent.click(screen.getByTestId("rf-connect"));

    // 保存 = 新 workflow_version。
    fireEvent.click(screen.getByTestId("workflow-save-submit"));
    const feedback = await screen.findByTestId("workflow-feedback");
    await waitFor(() => expect(feedback).toHaveTextContent("已保存为新版本"));
  });

  it("8 类节点面板齐备", async () => {
    renderDesigner();
    await screen.findByTestId("workflow-item-Onboarding");
    for (const nodeType of [
      "AGENT",
      "TOOL",
      "MCP",
      "CONDITION",
      "PARALLEL",
      "LOOP",
      "HUMAN_APPROVAL",
      "END",
    ]) {
      expect(screen.getByTestId(`add-node-${nodeType}`)).toBeInTheDocument();
    }
  });

  it("保存 = 新 workflow_version：发布载荷含既有 + 新增节点与连线，版本列表追加新版本（U-P2-30 硬口径）", async () => {
    // 发布接口捕获请求载荷，并让版本列表在发布后追加 v2（不可变：v1 保留）。
    let versions = [WORKFLOW_VERSION];
    const V2 = { ...WORKFLOW_VERSION, id: "wfv2", version: "v2" };
    let published: {
      nodes: Array<{ key: string }>;
      edges: unknown[];
      entry: string | null;
    } | null = null;
    server.use(
      http.get("/api/v1/workflows/:workflowId/versions", () => shell(versions)),
      http.post("/api/v1/workflows/:workflowId/publish", async ({ request }) => {
        published = (await request.json()) as typeof published;
        versions = [...versions, V2];
        return shell(V2, 201);
      }),
    );

    renderDesigner();

    // 选择既有 Workflow → 载入 v1 快照（n1 / n2）。
    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    expect(screen.getByTestId("rf-node-n2")).toBeInTheDocument();

    // 加节点 + 连线。
    fireEvent.click(screen.getByTestId("add-node-TOOL"));
    await screen.findByTestId("rf-node-n3");
    fireEvent.click(screen.getByTestId("rf-connect"));

    // 保存 = 新 workflow_version（服务端返回 v2）。
    fireEvent.click(screen.getByTestId("workflow-save-submit"));
    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent("已保存为新版本 v2");

    // 发布载荷断言：nodes 含 n1/n2（既有）+ n3（新增）；保留连线；entry = 首节点。
    expect(published).not.toBeNull();
    expect(published!.nodes.map((node) => node.key).sort()).toEqual(["n1", "n2", "n3"]);
    expect(published!.edges.length).toBeGreaterThanOrEqual(1);
    expect(published!.entry).toBe("n1");

    // 版本列表追加新版本（v2 出现；不可变历史保留）。
    // 注意：画布版本标签也含 `v2` → 断言限定在版本列表内，避免多元素歧义。
    const versionList = screen.getByTestId("workflow-version-list");
    expect(await within(versionList).findByText("v2")).toBeInTheDocument();
    expect(within(versionList).getByText("v1")).toBeInTheDocument();
  });

  it("工作流空列表 → 内联空态，且不渲染聊天示例 chips（B-21 回归）", async () => {
    server.use(http.get("/api/v1/workflows", () => shell([])));

    renderDesigner();

    // 空态：内联文案（列表容器 testid 保留；先等加载态让位给空态）。
    await waitFor(() =>
      expect(screen.getByTestId("workflow-list")).toHaveTextContent("还没有工作流"),
    );
    expect(screen.getByTestId("workflow-list")).toHaveTextContent("在下方输入名称创建第一个");

    // 回归断言：不再回落到聊天示例 chips（EmptyState 缺省 chips）。
    expect(screen.queryByText(/产品手册 v7 整理成 FAQ/)).toBeNull();
    expect(screen.queryByText(/检索知识库并总结要点/)).toBeNull();
    expect(screen.queryByTestId("empty-state")).toBeNull();
  });

  it("重命名：菜单 → 重命名 → PUT 只传 { name }", async () => {
    let renameBody: unknown = null;
    let renameUrl: string | null = null;
    server.use(
      http.put("/api/v1/workflows/:workflowId", async ({ request, params }) => {
        renameUrl = String(params.workflowId);
        renameBody = await request.json();
        return shell({ ...WORKFLOW, name: "Onboarding v2" });
      }),
    );

    renderDesigner();

    // 打开行尾 ⋯ 菜单 → 点「重命名」。
    const more = await screen.findByTestId("workflow-more-Onboarding");
    openDropdown(more);
    fireEvent.click(await screen.findByTestId("workflow-rename-Onboarding"));

    // 弹窗预填当前名称。
    const dialog = await screen.findByTestId("workflow-rename-dialog");
    expect(dialog).toBeInTheDocument();
    const input = screen.getByTestId("workflow-rename-input") as HTMLInputElement;
    expect(input.value).toBe("Onboarding");

    fireEvent.change(input, { target: { value: "Onboarding v2" } });
    fireEvent.click(screen.getByTestId("workflow-rename-submit"));

    await waitFor(() => expect(renameBody).toEqual({ name: "Onboarding v2" }));
    expect(renameUrl).toBe(WORKFLOW.id);
    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent("已重命名");
    await waitFor(() => expect(screen.queryByTestId("workflow-rename-dialog")).toBeNull());
  });

  it("删除：确认后调用 DELETE /workflows/{id}，并清空当前画布", async () => {
    let deletedId: string | null = null;
    server.use(
      http.delete("/api/v1/workflows/:workflowId", ({ params }) => {
        deletedId = String(params.workflowId);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderDesigner();

    // 先选中该工作流（画布载入 n1 / n2）。
    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");

    openDropdown(screen.getByTestId("workflow-more-Onboarding"));
    fireEvent.click(await screen.findByTestId("workflow-delete-Onboarding"));

    expect(await screen.findByText("删除工作流")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("workflow-delete-confirm"));

    await waitFor(() => expect(deletedId).toBe(WORKFLOW.id));
    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent("已删除");
    // 删除的是当前选中 → 画布清空、标题回到「未选择工作流」。
    await waitFor(() => expect(screen.queryByTestId("rf-node-n1")).toBeNull());
    expect(screen.getByText("未选择工作流")).toBeInTheDocument();
  });

  it("版本载入：点「载入」把该版本 definition 回灌画布（画布预览，保存仍生成新版本）", async () => {
    const V1 = {
      ...WORKFLOW_VERSION,
      id: "wfv1",
      version: "v1",
      definition: {
        nodes: [
          { key: "a1", type: "AGENT", config: {}, position: { x: 40, y: 40 } },
          { key: "a2", type: "END", config: {}, position: { x: 240, y: 40 } },
        ],
        edges: [{ from: "a1", to: "a2", condition: null }],
        entry: "a1",
      },
    };
    const V2 = {
      ...WORKFLOW_VERSION,
      id: "wfv2",
      version: "v2",
      definition: {
        nodes: [{ key: "b1", type: "TOOL", config: {}, position: { x: 40, y: 40 } }],
        edges: [],
        entry: "b1",
      },
    };
    server.use(http.get("/api/v1/workflows/:workflowId/versions", () => shell([V1, V2])));

    renderDesigner();

    // 选中工作流 → 自动载入最新版本（v2 → b1）。
    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-b1");
    expect(screen.getByTestId("workflow-canvas-version")).toHaveTextContent("v2 · 节点 1 · 连线 0");

    // 载入 v1 → 画布换成 a1 / a2。
    fireEvent.click(screen.getByTestId("workflow-version-load-v1"));
    await screen.findByTestId("rf-node-a1");
    expect(screen.getByTestId("rf-node-a2")).toBeInTheDocument();
    expect(screen.queryByTestId("rf-node-b1")).toBeNull();

    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent(
      "已载入 v1（保存仍生成新版本）",
    );
  });

  it("画布版本标签：载入历史版本标「（历史）」，保存出新版本后回到最新（P2 回归）", async () => {
    const V1 = {
      ...WORKFLOW_VERSION,
      id: "wfv1",
      version: "v1",
      definition: {
        nodes: [
          { key: "a1", type: "AGENT", config: {}, position: { x: 40, y: 40 } },
          { key: "a2", type: "END", config: {}, position: { x: 240, y: 40 } },
        ],
        edges: [{ from: "a1", to: "a2", condition: null }],
        entry: "a1",
      },
    };
    const V2 = {
      ...WORKFLOW_VERSION,
      id: "wfv2",
      version: "v2",
      definition: {
        nodes: [{ key: "b1", type: "TOOL", config: {}, position: { x: 40, y: 40 } }],
        edges: [],
        entry: "b1",
      },
    };
    const V3 = {
      ...WORKFLOW_VERSION,
      id: "wfv3",
      version: "v3",
      definition: {
        nodes: [
          { key: "a1", type: "AGENT", config: {}, position: { x: 40, y: 40 } },
          { key: "a2", type: "END", config: {}, position: { x: 240, y: 40 } },
        ],
        edges: [{ from: "a1", to: "a2", condition: null }],
        entry: "a1",
      },
    };
    let versions = [V1, V2];
    server.use(
      http.get("/api/v1/workflows/:workflowId/versions", () => shell(versions)),
      http.post("/api/v1/workflows/:workflowId/publish", () => {
        versions = [...versions, V3];
        return shell(V3, 201);
      }),
    );

    renderDesigner();

    // 选中工作流 → 自动载入最新版 v2：标签不带「历史」。
    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-b1");
    const label = await screen.findByTestId("workflow-canvas-version");
    expect(label).toHaveTextContent("v2");
    expect(label).not.toHaveTextContent("历史");

    // 显式载入最新版 v2 → 仍不带「历史」（边界：同版本不算历史）。
    fireEvent.click(screen.getByTestId("workflow-version-load-v2"));
    expect(await screen.findByTestId("workflow-canvas-version")).toHaveTextContent(
      "v2 · 节点 1 · 连线 0",
    );

    // 载入历史版 v1 → 标签变 `v1（历史） · 节点 2 · 连线 1`（琥珀提示不是最新）。
    fireEvent.click(screen.getByTestId("workflow-version-load-v1"));
    await screen.findByTestId("rf-node-a1");
    const historical = await screen.findByTestId("workflow-canvas-version");
    expect(historical).toHaveTextContent("v1（历史） · 节点 2 · 连线 1");

    // 保存（基于该历史版再生成新版本 v3）→ 画布版本回到最新，不再标「历史」。
    fireEvent.click(screen.getByTestId("workflow-save-submit"));
    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent("已保存为新版本 v3");
    await waitFor(() =>
      expect(screen.getByTestId("workflow-canvas-version")).toHaveTextContent("v3"),
    );
    expect(screen.getByTestId("workflow-canvas-version")).not.toHaveTextContent("历史");
    // 版本列表追加 v3（不可变历史保留 v1 / v2）；断言限定在版本列表内（画布标签也含 v3）。
    const versionList = screen.getByTestId("workflow-version-list");
    expect(await within(versionList).findByText("v3")).toBeInTheDocument();
  });

  // -- 运行闭环（POST /run + 重放快照 + 取消） ------------------------------

  it("运行：点「运行」→ POST /workflows/{id}/run（显式 Accept: application/json）→ 就地展开运行面板", async () => {
    let runUrl: string | null = null;
    let runBody: unknown = null;
    let runAccept: string | null = null;
    server.use(
      http.post("/api/v1/workflows/:workflowId/run", async ({ request, params }) => {
        runUrl = String(params.workflowId);
        runBody = await request.json();
        runAccept = request.headers.get("accept");
        return HttpResponse.json(WORKFLOW_RUN_DIGEST);
      }),
    );

    renderDesigner();

    // 未选择工作流 → 运行按钮禁用（防无目标运行）。
    expect(await screen.findByTestId("workflow-run")).toBeDisabled();

    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    await waitFor(() => expect(screen.getByTestId("workflow-run")).toBeEnabled());

    fireEvent.click(screen.getByTestId("workflow-run"));

    // 面板就地展开（非弹层）：状态 + 短 run id + 节点行。
    const panel = await screen.findByTestId("workflow-run-panel");
    expect(panel).toBeInTheDocument();
    expect(screen.getByTestId("workflow-run-id")).toHaveTextContent("#a1b2");
    expect(screen.getByTestId("workflow-run-id")).toHaveAttribute("title", WORKFLOW_RUN.run_id);
    expect(await screen.findByTestId("workflow-run-node-n1")).toBeInTheDocument();

    // 请求契约：URL / 载荷（INLINE 同步）/ Accept 必须显式 json（否则后端走 SSE）。
    expect(runUrl).toBe(WORKFLOW.id);
    expect(runBody).toEqual({ execution_mode: "INLINE", trigger: "user", input: {} });
    expect(runAccept ?? "").toContain("application/json");
    expect(runAccept ?? "").not.toContain("*/*");

    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent(
      "运行结束（SUCCEEDED）",
    );
  });

  it("运行面板：节点运行态 ≥2 且状态不同，展示尝试次数与耗时；终态时取消按钮禁用", async () => {
    renderDesigner();

    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    fireEvent.click(screen.getByTestId("workflow-run"));

    const nodes = await screen.findByTestId("workflow-run-nodes");
    const rows = within(nodes).getAllByRole("listitem");
    expect(rows.length).toBeGreaterThanOrEqual(2);

    // 两个节点、不同状态（n1 SUCCEEDED / n2 SKIPPED）。
    expect(rows[0]).toHaveTextContent("n1");
    expect(rows[0]).toHaveTextContent("SUCCEEDED");
    expect(rows[1]).toHaveTextContent("n2");
    expect(rows[1]).toHaveTextContent("SKIPPED");
    expect(rows[0]).toHaveTextContent("尝试 1");

    // 节点耗时（2s → `2.0s`）+ 节点计数。
    expect(screen.getByTestId("workflow-run-node-duration-n1")).toHaveTextContent("2.0s");
    expect(screen.getByTestId("workflow-run-node-count")).toHaveTextContent("2");
    expect(screen.getByTestId("workflow-run-status")).toHaveTextContent("SUCCEEDED");
    expect(screen.getByTestId("workflow-run-trigger")).toHaveTextContent("user");
    expect(screen.getByTestId("workflow-run-duration")).toHaveTextContent("2.0s");

    // 终态（SUCCEEDED）→ 不可取消。
    await waitFor(() => expect(screen.getByTestId("workflow-run-cancel")).toBeDisabled());
  });

  it("运行失败：状态与错误条一并展示（消息来自重放快照 error）", async () => {
    server.use(
      http.post("/api/v1/workflows/:workflowId/run", () =>
        HttpResponse.json({
          ...WORKFLOW_RUN_DIGEST,
          status: "FAILED",
          error: "节点 n1 执行失败",
        }),
      ),
      http.get("/api/v1/workflows/:workflowId/runs/:runId", () =>
        shell({ ...WORKFLOW_RUN, status: "FAILED", error: "节点 n1 执行失败" }),
      ),
    );

    renderDesigner();

    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    fireEvent.click(screen.getByTestId("workflow-run"));

    const errorBar = await screen.findByTestId("workflow-run-error");
    expect(errorBar).toHaveTextContent("节点 n1 执行失败");
    expect(screen.getByTestId("workflow-run-status")).toHaveTextContent("FAILED");
    expect(await screen.findByTestId("workflow-feedback")).toHaveTextContent("运行结束（FAILED）");
    await waitFor(() => expect(screen.getByTestId("workflow-run-cancel")).toBeDisabled());
  });

  it("非终态可取消：POST .../cancel → 面板转 CANCELLED；「收起」关闭面板", async () => {
    let cancelUrl: string | null = null;
    let cancelled = false;
    server.use(
      http.post("/api/v1/workflows/:workflowId/run", () =>
        HttpResponse.json({ ...WORKFLOW_RUN_DIGEST, status: "RUNNING" }),
      ),
      http.get("/api/v1/workflows/:workflowId/runs/:runId", () =>
        shell({ ...WORKFLOW_RUN, status: cancelled ? "CANCELLED" : "RUNNING" }),
      ),
      http.post("/api/v1/workflows/:workflowId/runs/:runId/cancel", ({ params }) => {
        cancelUrl = `${String(params.workflowId)}/${String(params.runId)}`;
        cancelled = true;
        return shell(WORKFLOW_RUN_DETAIL);
      }),
    );

    renderDesigner();

    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    fireEvent.click(screen.getByTestId("workflow-run"));

    const cancelButton = await screen.findByTestId("workflow-run-cancel");
    await waitFor(() => expect(cancelButton).toBeEnabled());
    fireEvent.click(cancelButton);

    await waitFor(() =>
      expect(screen.getByTestId("workflow-run-feedback")).toHaveTextContent(
        "已请求取消（CANCELLED）",
      ),
    );
    expect(cancelUrl).toBe(`${WORKFLOW.id}/${WORKFLOW_RUN.run_id}`);
    await waitFor(() =>
      expect(screen.getByTestId("workflow-run-status")).toHaveTextContent("CANCELLED"),
    );

    // 收起 → 面板关闭（画布恢复）。
    fireEvent.click(screen.getByTestId("workflow-run-collapse"));
    await waitFor(() => expect(screen.queryByTestId("workflow-run-panel")).toBeNull());
  });

  it("待审批（WAITING_APPROVAL）为**非终态**：取消可用，挂起节点行标注「待审批」（不跳转）", async () => {
    server.use(
      http.post("/api/v1/workflows/:workflowId/run", () =>
        HttpResponse.json({ ...WORKFLOW_RUN_DIGEST, status: "WAITING_APPROVAL" }),
      ),
      http.get("/api/v1/workflows/:workflowId/runs/:runId", () =>
        shell({
          ...WORKFLOW_RUN,
          status: "WAITING_APPROVAL",
          nodes: [
            { ...WORKFLOW_RUN.nodes[0] },
            {
              ...WORKFLOW_RUN.nodes[1],
              node_key: "n3",
              status: "WAITING_APPROVAL",
              approval_id: "apr1",
              completed_at: null,
            },
          ],
        }),
      ),
    );

    renderDesigner();

    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    fireEvent.click(screen.getByTestId("workflow-run"));

    // 非终态：状态徽标显示 WAITING_APPROVAL，取消按钮**可点**（终态才禁用）。
    expect(await screen.findByTestId("workflow-run-status")).toHaveTextContent("WAITING_APPROVAL");
    await waitFor(() => expect(screen.getByTestId("workflow-run-cancel")).toBeEnabled());

    // 挂起审批的节点行额外标注「待审批」（仅标注，不做跳转/联动）。
    const approvalChip = await screen.findByTestId("workflow-run-node-approval-n3");
    expect(approvalChip).toHaveTextContent("待审批");
    expect(approvalChip).toHaveAttribute("title", "approval_id: apr1");
    // 未挂起审批的节点行不出现该标注。
    expect(screen.queryByTestId("workflow-run-node-approval-n1")).toBeNull();
  });

  it("运行详情加载失败（500）：**错误态不轮询** —— 越过一个轮询周期后请求仍只有 1 次", async () => {
    let replayCalls = 0;
    server.use(
      http.get("/api/v1/workflows/:workflowId/runs/:runId", () => {
        replayCalls += 1;
        return HttpResponse.json(
          { code: "INTERNAL_ERROR", message: "运行详情读取失败", data: {} },
          { status: 500 },
        );
      }),
    );

    renderDesigner();

    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    fireEvent.click(screen.getByTestId("workflow-run"));

    // 四态之错误态：面板给出错误条 + 显式「重试」（不作为隐式轮询的替代）。
    const errorPanel = await screen.findByTestId("workflow-run-panel-error");
    expect(errorPanel).toHaveTextContent("运行详情读取失败");
    expect(screen.getByTestId("workflow-run-retry")).toBeInTheDocument();
    // 首拉只发生一次（`retry: false` → 不含 react-query 自身重试）。
    expect(replayCalls).toBe(1);

    // 越过一个轮询周期（2s）+ 余量：错误态**不得**再发请求（此断言即为无限轮询的守卫）。
    await new Promise((resolve) => {
      setTimeout(resolve, 2_600);
    });
    expect(replayCalls).toBe(1);

    // 显式重试才会再发一次（证明「停止轮询」没有把「手动重试」一起关掉）。
    fireEvent.click(screen.getByTestId("workflow-run-retry"));
    await waitFor(() => expect(replayCalls).toBe(2));
  });

  // V0.4.6 缺陷 L-4 / 批次 B2：默认语言 en 下不得露中文（页头 / 空态 / 面板 / 节点名）。
  it("i18n：切到 en → 页头 / 空态 / 节点名 / 工具栏为英文，不残留中文", async () => {
    server.use(http.get("/api/v1/workflows", () => shell([])));
    useI18nStore.setState({ language: "en" });
    renderDesigner();

    await waitFor(() =>
      expect(screen.getByTestId("workflow-list")).toHaveTextContent("No workflows yet"),
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Workflow Designer");
    expect(screen.getByTestId("workflow-list")).toHaveTextContent(
      "Type a name below to create your first one",
    );
    expect(screen.getByTestId("add-node-AGENT")).toHaveTextContent("Agent");
    expect(screen.getByTestId("workflow-save-submit")).toHaveTextContent("Save as new version");

    // 关键中文文案均已切到 en 资源。
    expect(screen.queryByText("还没有工作流")).toBeNull();
    expect(screen.queryByText("工作流编排")).toBeNull();
    expect(screen.queryByText("智能体")).toBeNull();
  });
});
