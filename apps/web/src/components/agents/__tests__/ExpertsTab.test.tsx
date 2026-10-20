// ---------------------------------------------------------------------------
// WBTimeAI · 专家 Tab 单测（V0.4.6 · D-UI 优化波）
//
// 覆盖（对齐施工单 §8）：
//   ① 搜索命中描述（name 不含关键词）；② 状态筛选；③ 类型筛选；④ 搜索 + 状态叠加；
//   ⑤ 排序（最近更新 / 名称）；⑥ 草稿 / 已发布 / 已归档的主操作文案；
//   ⑦ 列表视图切换；⑧ 真空态三步 + CTA；⑨ 筛选空态 + 清除筛选；
//   ⑩ 错误态 + 重试调用 refetch；⑪ 整卡 Enter 进详情（断言路由）。
//
// 数据源 `useAgents` 以 `vi.hoisted` 可变桩替代（零网络）；语言固定 `zh-CN`（产品默认中文界面）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExpertsTab } from "@/components/agents/ExpertsTab";
import { useI18nStore } from "@/stores/i18nStore";
import type { AgentResponse } from "@/types";

/** 可变的 `useAgents` 桩状态。 */
const mockState = vi.hoisted(() => ({
  agents: [] as AgentResponse[],
  isLoading: false,
  isError: false,
  error: null as unknown,
  refetch: vi.fn(),
}));

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: mockState.agents,
    isLoading: mockState.isLoading,
    isError: mockState.isError,
    error: mockState.error,
    refetch: mockState.refetch,
  }),
}));

/** 五个真实字段构造的样例（覆盖三种状态 × 四种类型）。 */
const FIXTURES: readonly AgentResponse[] = [
  {
    id: "a1",
    name: "代码评审助手",
    description: "针对 Pull Request 给出结构化评审意见，聚焦安全与可维护性。",
    type: "PRIMARY",
    status: "ACTIVE",
    created_by: "u1",
    created_at: "2026-10-01T09:00:00",
    updated_at: "2026-10-12T09:00:00",
  },
  {
    id: "a2",
    name: "周报撰写助手",
    description: "按项目维度汇总本周提交与任务进展，输出周报初稿。",
    type: "PRIMARY",
    status: "ACTIVE",
    created_by: "u1",
    created_at: "2026-09-20T09:00:00",
    updated_at: "2026-10-16T09:00:00",
  },
  {
    id: "a3",
    name: "日志归因分析",
    description: "对日志片段做异常聚类与根因假设排序。",
    type: "SUB_AGENT",
    status: "DRAFT",
    created_by: "u1",
    created_at: "2026-10-01T09:00:00",
    updated_at: "2026-10-01T09:00:00",
  },
  {
    id: "a4",
    name: "合同要点抽取",
    description: "从合同文本抽取主体、期限与违约条款，输出结构化字段。",
    type: "WORKFLOW_AGENT",
    status: "ACTIVE",
    created_by: "u1",
    created_at: "2026-08-30T09:00:00",
    updated_at: "2026-09-01T09:00:00",
  },
  {
    id: "a5",
    name: "SQL 解释器",
    description: "把自然语言问题转成 SQL 并解释执行计划。",
    type: "PRIMARY",
    status: "ARCHIVED",
    created_by: "u1",
    created_at: "2026-07-01T09:00:00",
    updated_at: "2026-08-01T09:00:00",
  },
];

/** 位置探针：暴露当前 `pathname` / `search` 以断言卡片 / 行跳转。 */
function LocationProbe() {
  const location = useLocation();
  return (
    <>
      <div data-testid="location-path">{location.pathname}</div>
      <div data-testid="location-search">{location.search}</div>
    </>
  );
}

/** 渲染专家 Tab（MemoryRouter + 位置探针）。 */
function renderTab(onCreate: () => void = vi.fn()): () => void {
  render(
    <MemoryRouter initialEntries={["/agents"]}>
      <ExpertsTab onCreate={onCreate} />
      <LocationProbe />
    </MemoryRouter>,
  );
  return onCreate;
}

/** 取当前渲染出的卡片 id 顺序（排除卡内主操作按钮的 `agent-card-primary-*`）。 */
function cardIds(): string[] {
  return screen
    .getAllByTestId(/^agent-card-/)
    .filter((element) => !(element.getAttribute("data-testid") ?? "").includes("primary"))
    .map((element) => (element.getAttribute("data-testid") ?? "").replace("agent-card-", ""));
}

beforeEach(() => {
  mockState.agents = FIXTURES.map((agent) => ({ ...agent }));
  mockState.isLoading = false;
  mockState.isError = false;
  mockState.error = null;
  mockState.refetch.mockReset();
  useI18nStore.setState({ language: "zh-CN" });
});

describe("ExpertsTab · 搜索与筛选", () => {
  it("① 搜索命中描述（名称不含关键词）", () => {
    renderTab();
    expect(screen.getByTestId("agent-card-a1")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("agents-search-experts"), {
      target: { value: "pull request" },
    });
    expect(cardIds()).toEqual(["a1"]);

    // 清除按钮出现并复位。
    fireEvent.click(screen.getByTestId("agents-search-clear"));
    expect(cardIds()).toHaveLength(5);
    expect(screen.queryByTestId("agents-search-clear")).toBeNull();
  });

  it("② 状态筛选：已发布 / 草稿", () => {
    renderTab();

    fireEvent.click(screen.getByTestId("agents-status-published"));
    expect(cardIds()).toEqual(["a2", "a1", "a4"]);
    expect(screen.getByTestId("agents-status-published")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("agents-status-all")).toHaveAttribute("aria-selected", "false");

    fireEvent.click(screen.getByTestId("agents-status-draft"));
    expect(cardIds()).toEqual(["a3"]);
  });

  it("③ 类型筛选（真实字段 type）", () => {
    renderTab();

    fireEvent.change(screen.getByTestId("agents-type-filter"), {
      target: { value: "WORKFLOW_AGENT" },
    });
    expect(cardIds()).toEqual(["a4"]);

    fireEvent.change(screen.getByTestId("agents-type-filter"), { target: { value: "all" } });
    expect(cardIds()).toHaveLength(5);
  });

  it("④ 搜索 + 状态叠加 → 无命中后清除筛选", () => {
    renderTab();

    fireEvent.change(screen.getByTestId("agents-search-experts"), { target: { value: "汇总" } });
    expect(cardIds()).toEqual(["a2"]);

    fireEvent.click(screen.getByTestId("agents-status-draft"));
    expect(screen.queryByTestId("agents-experts-grid")).toBeNull();
    expect(screen.getByTestId("agents-experts-no-match")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("agents-clear-filters"));
    expect(cardIds()).toHaveLength(5);
    expect(screen.getByTestId("agents-status-all")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("agents-search-experts")).toHaveValue("");
  });

  it("⑤ 排序：默认最近更新倒序，可切名称 A→Z", () => {
    renderTab();
    expect(cardIds()).toEqual(["a2", "a1", "a3", "a4", "a5"]);

    fireEvent.change(screen.getByTestId("agents-sort"), { target: { value: "name" } });
    const ids = cardIds();
    // 拼音序：代码评审助手 < 日志归因分析 < 周报撰写助手（SQL 解释器为拉丁字母，位置由 ICU 决定）。
    expect(ids.indexOf("a1")).toBeLessThan(ids.indexOf("a3"));
    expect(ids.indexOf("a3")).toBeLessThan(ids.indexOf("a2"));
  });
});

describe("ExpertsTab · 卡片主操作与视图", () => {
  it("⑥ 主操作随状态切换：草稿=完善并发布 / 已发布=开始对话 / 已归档=只读", () => {
    renderTab();

    expect(screen.getByTestId("agent-card-primary-a3")).toHaveTextContent("完善并发布");
    expect(screen.getByTestId("agent-card-primary-a1")).toHaveTextContent("开始对话");
    expect(screen.getByTestId("agent-card-primary-a5")).toHaveTextContent("已归档，仅可查看");
  });

  it("⑦ 列表视图切换（表格无版本号列）", () => {
    renderTab();
    expect(screen.getByTestId("agents-view-grid")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByTestId("agents-view-list"));
    expect(screen.getByTestId("agents-experts-list")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-experts-grid")).toBeNull();
    expect(screen.getByTestId("agents-view-list")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("agent-row-a3")).toBeInTheDocument();
    expect(screen.getByTestId("agents-experts-list").textContent ?? "").not.toMatch(/v\d/);

    fireEvent.click(screen.getByTestId("agents-view-grid"));
    expect(screen.getByTestId("agents-experts-grid")).toBeInTheDocument();
  });
});

describe("ExpertsTab · 非正常态", () => {
  it("⑧ 真空态：三步说明 + 主 CTA", () => {
    mockState.agents = [];
    const onCreate = renderTab();

    expect(screen.getByTestId("agents-experts-empty")).toBeInTheDocument();
    expect(screen.getByText("还没有专家")).toBeInTheDocument();
    expect(screen.getByText("选择模型")).toBeInTheDocument();
    expect(screen.getByText("配 Prompt 与工具")).toBeInTheDocument();
    expect(screen.getByText("发布并召唤")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("agents-empty-create"));
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it("⑨ 筛选后为空：提示 + 清除筛选", () => {
    renderTab();

    fireEvent.change(screen.getByTestId("agents-search-experts"), {
      target: { value: "不存在的专家名" },
    });
    expect(screen.getByTestId("agents-experts-no-match")).toHaveTextContent("没有匹配的专家");

    fireEvent.click(screen.getByTestId("agents-clear-filters"));
    expect(cardIds()).toHaveLength(5);
  });

  it("⑩ 接口错误优先于空态，重试调用 refetch", () => {
    mockState.isError = true;
    mockState.error = new Error("boom");
    renderTab();

    const panel = screen.getByTestId("agents-experts-error");
    expect(panel).toHaveTextContent("加载失败");
    expect(panel).toHaveTextContent("boom");
    expect(screen.queryByTestId("agents-experts-empty")).toBeNull();

    fireEvent.click(screen.getByTestId("agents-retry"));
    expect(mockState.refetch).toHaveBeenCalledTimes(1);
  });
});

describe("ExpertsTab · 无障碍跳转", () => {
  it("⑪ 整卡 Enter 进入详情", () => {
    renderTab();
    expect(screen.getByTestId("location-path")).toHaveTextContent("/agents");

    fireEvent.keyDown(screen.getByTestId("agent-card-a1"), { key: "Enter" });
    expect(screen.getByTestId("location-path").textContent).toBe("/agents/a1");
  });

  it("卡片主操作 stopPropagation：草稿卡「完善并发布」只跳一次详情", () => {
    renderTab();

    fireEvent.click(screen.getByTestId("agent-card-primary-a3"));
    expect(screen.getByTestId("location-path").textContent).toBe("/agents/a3");
  });
});

describe("ExpertsTab · 键盘冲突（卡内按钮 Enter 不被整卡抢）", () => {
  it("已发布卡「开始对话」Enter：整卡不抢，按钮自身落到 /chat?agent=<id>", () => {
    renderTab();
    const primary = screen.getByTestId("agent-card-primary-a1");

    // ① 整卡不处理卡内按钮的 Enter：事件未被 preventDefault（浏览器据此会合成 click）。
    expect(fireEvent.keyDown(primary, { key: "Enter" })).toBe(true);
    expect(screen.getByTestId("location-path").textContent).toBe("/agents");

    // ② 合成 click（jsdom 不会由 Enter 自动合成，这里显式复现浏览器行为）。
    fireEvent.click(primary);
    expect(screen.getByTestId("location-path").textContent).toBe("/chat");
    expect(screen.getByTestId("location-search").textContent).toBe("?agent=a1");
  });

  it("草稿卡「完善并发布」Enter：整卡不抢，按钮自身落到 /agents/<id>", () => {
    renderTab();
    const primary = screen.getByTestId("agent-card-primary-a3");

    expect(fireEvent.keyDown(primary, { key: "Enter" })).toBe(true);
    expect(screen.getByTestId("location-path").textContent).toBe("/agents");

    fireEvent.click(primary);
    expect(screen.getByTestId("location-path").textContent).toBe("/agents/a3");
  });

  it("卡片本身获得焦点时 Enter 仍进详情（守卫只排除内部元素）", () => {
    renderTab();

    expect(fireEvent.keyDown(screen.getByTestId("agent-card-a2"), { key: "Enter" })).toBe(false);
    expect(screen.getByTestId("location-path").textContent).toBe("/agents/a2");
  });

  it("列表视图行内主按钮 Enter：行不抢，按钮自身落到 /chat?agent=<id>", () => {
    renderTab();
    fireEvent.click(screen.getByTestId("agents-view-list"));

    const rowButton = within(screen.getByTestId("agent-row-a1")).getByRole("button", {
      name: "开始对话",
    });
    expect(fireEvent.keyDown(rowButton, { key: "Enter" })).toBe(true);
    expect(screen.getByTestId("location-path").textContent).toBe("/agents");

    fireEvent.click(rowButton);
    expect(screen.getByTestId("location-path").textContent).toBe("/chat");
    expect(screen.getByTestId("location-search").textContent).toBe("?agent=a1");
  });

  it("列表视图行本身 Enter 仍进详情", () => {
    renderTab();
    fireEvent.click(screen.getByTestId("agents-view-list"));

    fireEvent.keyDown(screen.getByTestId("agent-row-a2"), { key: "Enter" });
    expect(screen.getByTestId("location-path").textContent).toBe("/agents/a2");
  });
});
