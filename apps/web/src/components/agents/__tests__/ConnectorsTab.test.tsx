// ---------------------------------------------------------------------------
// WBTimeAI · 连接器 Tab 单测（V0.4.6 B-15 · 三 Tab 统一改版）
//
// 覆盖：分区头计数 / 传输筛选 / 状态分段（真实字段 status）/ 搜索匹配 endpoint+command /
//       自定义连接器 disabled / MCP Hub 虚线卡 / 真空态 CTA（受控弹窗）/ 筛选空 + 清除 /
//       错误态 + 重试 / MCP 服务管理弹窗受控开合。
//
// 数据源 `useMcpServers` 以可变桩替代（零网络；`McpServersDialog` 同源共用桩）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { installRadixStubs } from "@/components/agents/__tests__/jsdomStubs";
import { ConnectorsTab } from "@/components/agents/ConnectorsTab";
import { useI18nStore } from "@/stores/i18nStore";

installRadixStubs();

/** 可变的 `useMcpServers` 桩状态。 */
const mockState = vi.hoisted(() => ({
  servers: [] as Array<Record<string, unknown>>,
  isLoading: false,
  isError: false,
  error: null as unknown,
  refetch: vi.fn(),
}));

vi.mock("@/hooks/useMcp", () => ({
  useMcpServers: () => ({
    data: mockState.servers,
    isLoading: mockState.isLoading,
    isError: mockState.isError,
    error: mockState.error,
    refetch: mockState.refetch,
  }),
}));

/** 两条真实字段构造的样例（stdio + ACTIVE / sse + 非 ACTIVE）。 */
const FIXTURES: readonly Record<string, unknown>[] = [
  {
    id: "m1",
    name: "filesystem",
    transport: "stdio",
    endpoint: null,
    command: "npx -y @modelcontextprotocol/server-fs",
    args: [],
    env_ref: {},
    status: "ACTIVE",
  },
  {
    id: "m2",
    name: "github",
    transport: "sse",
    endpoint: "https://mcp.github.com/sse",
    command: null,
    args: [],
    env_ref: {},
    status: "INACTIVE",
  },
];

/** 渲染连接器 Tab（受控 props + 返回 onManageOpenChange 桩）。 */
function renderConnectors(manageOpen = false): ReturnType<typeof vi.fn> {
  const onManageOpenChange = vi.fn();
  render(<ConnectorsTab manageOpen={manageOpen} onManageOpenChange={onManageOpenChange} />);
  return onManageOpenChange;
}

beforeEach(() => {
  mockState.servers = FIXTURES.map((server) => ({ ...server }));
  mockState.isLoading = false;
  mockState.isError = false;
  mockState.error = null;
  mockState.refetch.mockReset();
  useI18nStore.setState({ language: "zh-CN" });
});

describe("ConnectorsTab · 工具栏与卡片", () => {
  it("分区头计数：共 N 个 · M 个启用", () => {
    renderConnectors();

    expect(screen.getByText("我的连接器")).toBeInTheDocument();
    expect(screen.getByText("共 2 个 · 1 个启用")).toBeInTheDocument();
  });

  it("传输下拉：选项随数据去重，筛选生效", () => {
    renderConnectors();

    const options = [
      ...screen.getByTestId("agents-connectors-transport-filter").querySelectorAll("option"),
    ].map((option) => option.textContent);
    expect(options).toEqual(["全部传输", "sse", "stdio"]);

    fireEvent.change(screen.getByTestId("agents-connectors-transport-filter"), {
      target: { value: "sse" },
    });
    expect(screen.queryByTestId("agents-connector-card-m1")).toBeNull();
    expect(screen.getByTestId("agents-connector-card-m2")).toBeInTheDocument();
  });

  it("状态分段（真实字段 status）：已启用 = ACTIVE，计数按全量算", () => {
    renderConnectors();

    expect(screen.getByTestId("agents-connector-status-all")).toHaveTextContent("全部2");
    expect(screen.getByTestId("agents-connector-status-enabled")).toHaveTextContent("已启用1");
    expect(screen.getByTestId("agents-connector-status-disabled")).toHaveTextContent("未启用1");

    fireEvent.click(screen.getByTestId("agents-connector-status-enabled"));
    expect(screen.getByTestId("agents-connector-card-m1")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-connector-card-m2")).toBeNull();
    expect(screen.getByTestId("agents-connector-status-enabled")).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(screen.getByTestId("agents-connector-status-disabled"));
    expect(screen.queryByTestId("agents-connector-card-m1")).toBeNull();
    expect(screen.getByTestId("agents-connector-card-m2")).toBeInTheDocument();
  });

  it("搜索命中 endpoint 与 command（名称不含关键词）", () => {
    renderConnectors();

    fireEvent.change(screen.getByTestId("agents-search-connectors"), {
      target: { value: "github.com" },
    });
    expect(screen.getByTestId("agents-connector-card-m2")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-connector-card-m1")).toBeNull();

    fireEvent.change(screen.getByTestId("agents-search-connectors"), {
      target: { value: "modelcontextprotocol" },
    });
    expect(screen.getByTestId("agents-connector-card-m1")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-connector-card-m2")).toBeNull();
  });

  it("连接器卡：mono 端点行 + 状态点文案 + transport tag；整卡不可点", () => {
    renderConnectors();

    const card = screen.getByTestId("agents-connector-card-m1");
    expect(card).toHaveTextContent("filesystem");
    expect(card).toHaveTextContent("npx -y @modelcontextprotocol/server-fs");
    expect(card).toHaveTextContent("已启用");
    expect(card).toHaveTextContent("stdio");
    expect(card.tagName).toBe("ARTICLE");
    expect(card).not.toHaveAttribute("role");
  });

  it("「自定义连接器」disabled + title 提示（不再是可点死按钮）", () => {
    renderConnectors();

    const button = screen.getByTestId("agents-connectors-add-custom");
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "后续开放");
  });

  it("网格尾追加 MCP Hub 虚线展示卡（非按钮）", () => {
    renderConnectors();

    const hub = screen.getByTestId("agents-connectors-hub-card");
    expect(hub).toHaveTextContent("MCP Hub");
    expect(hub).toHaveTextContent("市场连接器目录（后续开放）");
    expect(hub.tagName).not.toBe("BUTTON");
  });
});

describe("ConnectorsTab · 非正常态", () => {
  it("真空态：统一空态面板 + CTA 打开受控 MCP 弹窗；工具栏不渲染", () => {
    mockState.servers = [];
    const onManageOpenChange = renderConnectors();

    expect(screen.getByTestId("agents-connectors-empty")).toBeInTheDocument();
    expect(screen.getByText("还没有连接器")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-connectors-toolbar")).toBeNull();

    fireEvent.click(screen.getByTestId("agents-connectors-empty-create"));
    expect(onManageOpenChange).toHaveBeenCalledWith(true);
  });

  it("筛选后为空：提示 + 清除筛选", () => {
    renderConnectors();

    fireEvent.change(screen.getByTestId("agents-search-connectors"), {
      target: { value: "不存在" },
    });
    expect(screen.getByTestId("agents-connectors-no-match")).toHaveTextContent("没有匹配的连接器");

    fireEvent.click(screen.getByTestId("agents-connectors-clear-filters"));
    expect(screen.getByTestId("agents-connector-card-m1")).toBeInTheDocument();
    expect(screen.getByTestId("agents-search-connectors")).toHaveValue("");
  });

  it("错误态优先于空态：面板含归一化 message，重试调用 refetch", () => {
    mockState.isError = true;
    mockState.error = new Error("mcp down");
    renderConnectors();

    const panel = screen.getByTestId("agents-connectors-error");
    expect(panel).toHaveTextContent("加载失败");
    expect(panel).toHaveTextContent("mcp down");
    expect(screen.queryByTestId("agents-connectors-empty")).toBeNull();

    fireEvent.click(screen.getByTestId("agents-connectors-retry"));
    expect(mockState.refetch).toHaveBeenCalledTimes(1);
  });
});

describe("ConnectorsTab · 受控弹窗", () => {
  it("MCP 服务管理弹窗受控：宿主置 manageOpen=true 渲染列表态，关闭回调 onManageOpenChange(false)", () => {
    const onManageOpenChange = renderConnectors(true);

    expect(screen.getByTestId("agents-mcp-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agents-mcp-list")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("dialog-close"));
    expect(onManageOpenChange).toHaveBeenCalledWith(false);
  });
});
