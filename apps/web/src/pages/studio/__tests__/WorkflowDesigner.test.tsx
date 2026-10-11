// ---------------------------------------------------------------------------
// Astra AI · WorkflowDesigner 单测（W6 / T2-35 · U-P2-30 / Q-76）
//
// 覆盖：**加节点 → 连线 → 保存 = 新 workflow_version**（不可变）。
// React Flow 以轻量 mock 替代（jsdom 无真实布局），交互经工具栏 + 连接按钮触发。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkflowDesigner } from "@/pages/studio/WorkflowDesigner";
import { useAuthStore } from "@/stores/authStore";
import { WORKFLOW_VERSION, shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

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

describe("WorkflowDesigner", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("加节点 → 连线 → 保存 = 新版本（不可变）", async () => {
    renderDesigner();

    // 选择既有 Workflow → 载入最新版本快照（n1 / n2）。
    fireEvent.click(await screen.findByTestId("workflow-item-Onboarding"));
    await screen.findByTestId("rf-node-n1");
    expect(screen.getByTestId("rf-node-n2")).toBeInTheDocument();

    // 工具栏：添加一个 TOOL 节点（n3）。
    fireEvent.click(screen.getByTestId("add-node-TOOL"));
    await screen.findByTestId("rf-node-n3");

    // 连线（↔ workflow_edge）。
    fireEvent.click(screen.getByTestId("rf-connect"));

    // 保存 = 新 workflow_version。
    fireEvent.click(screen.getByTestId("workflow-save-submit"));
    const feedback = await screen.findByTestId("workflow-feedback");
    await waitFor(() => expect(feedback).toHaveTextContent("已保存为新版本"));
  });

  it("8 类节点工具栏齐备", async () => {
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
    expect(await screen.findByText("v2")).toBeInTheDocument();
  });
});
