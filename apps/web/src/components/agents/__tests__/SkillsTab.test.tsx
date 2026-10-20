// ---------------------------------------------------------------------------
// WBTimeAI · 技能 Tab 单测（V0.4.6 B-15 · 三 Tab 统一改版）
//
// 覆盖：分组与市场虚线卡 / 分类筛选（含未分类）/ 搜索命中描述 / 启用开关本地态 /
//       已安装计数取全量 / 真空态 CTA（受控弹窗）/ 筛选空 + 清除 / 错误态 + 重试 /
//       添加技能弹窗受控开合。
//
// 数据源 `useSkills` 以可变桩替代（零网络；保留真实 `toSkillListItems` 投影）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { installRadixStubs } from "@/components/agents/__tests__/jsdomStubs";
import { SkillsTab } from "@/components/agents/SkillsTab";
import { useI18nStore } from "@/stores/i18nStore";

installRadixStubs();

/** 可变的 `useSkills` 桩状态。 */
const mockState = vi.hoisted(() => ({
  skills: [] as Array<Record<string, unknown>>,
  isLoading: false,
  isError: false,
  error: null as unknown,
  refetch: vi.fn(),
}));

vi.mock("@/hooks/useSkills", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/useSkills")>();
  return {
    ...actual,
    useSkills: () => ({
      data: mockState.skills,
      isLoading: mockState.isLoading,
      isError: mockState.isError,
      error: mockState.error,
      refetch: mockState.refetch,
    }),
  };
});

/** 三条真实字段构造的样例（覆盖 报告 / 数据库 / 未分类 三种分类）。 */
const FIXTURES: readonly Record<string, unknown>[] = [
  {
    id: "s1",
    name: "weekly-report",
    display_name: "周报生成器",
    description: "按项目维度汇总本周提交与任务进展",
    category: "报告",
    status: "PUBLISHED",
    created_by: "u1",
    created_at: "2026-10-15T09:00:00",
  },
  {
    id: "s2",
    name: "sql-check",
    display_name: "SQL 检查器",
    description: "检查 SQL 语义与性能风险",
    category: "数据库",
    status: "DRAFT",
    created_by: "u1",
    created_at: "2026-10-12T09:00:00",
  },
  {
    id: "s3",
    name: "misc-tool",
    display_name: "杂项工具",
    description: "未归类的小工具技能",
    category: "",
    status: "DRAFT",
    created_by: "u1",
    created_at: "2026-10-01T09:00:00",
  },
];

/** 渲染技能 Tab（受控 props + 返回 onAddOpenChange 桩）。 */
function renderSkills(addOpen = false): ReturnType<typeof vi.fn> {
  const onAddOpenChange = vi.fn();
  render(<SkillsTab addOpen={addOpen} onAddOpenChange={onAddOpenChange} />);
  return onAddOpenChange;
}

beforeEach(() => {
  mockState.skills = FIXTURES.map((skill) => ({ ...skill }));
  mockState.isLoading = false;
  mockState.isError = false;
  mockState.error = null;
  mockState.refetch.mockReset();
  useI18nStore.setState({ language: "zh-CN" });
});

describe("SkillsTab · 工具栏与分组", () => {
  it("分组：用户自定义承载全部技能；市场组恒空 → 虚线展示卡（非按钮）", () => {
    renderSkills();

    expect(screen.getByTestId("agents-skills-group-custom")).toBeInTheDocument();
    expect(screen.getByTestId("skill-card-s1")).toBeInTheDocument();
    expect(screen.getByTestId("skill-card-s2")).toBeInTheDocument();
    expect(screen.getByTestId("skill-card-s3")).toBeInTheDocument();

    const marketCard = screen.getByTestId("agents-skills-market-card");
    expect(marketCard).toHaveTextContent("技能市场即将开放");
    expect(marketCard).toHaveTextContent("开放后可一键安装市场技能");
    expect(marketCard.tagName).not.toBe("BUTTON");
  });

  it("分类下拉：选项随数据去重，空字符串分类显示「未分类」", () => {
    renderSkills();

    const options = [
      ...screen.getByTestId("agents-skills-category-filter").querySelectorAll("option"),
    ].map((option) => option.textContent);
    expect(options).toEqual(["全部分类", "报告", "数据库", "未分类"]);
  });

  it("分类筛选生效（真实字段 category）", () => {
    renderSkills();

    fireEvent.change(screen.getByTestId("agents-skills-category-filter"), {
      target: { value: "数据库" },
    });
    expect(screen.queryByTestId("skill-card-s1")).toBeNull();
    expect(screen.getByTestId("skill-card-s2")).toBeInTheDocument();
    expect(screen.queryByTestId("skill-card-s3")).toBeNull();

    // 未分类（空字符串分类）可被筛出。
    fireEvent.change(screen.getByTestId("agents-skills-category-filter"), {
      target: { value: "" },
    });
    expect(screen.queryByTestId("skill-card-s2")).toBeNull();
    expect(screen.getByTestId("skill-card-s3")).toBeInTheDocument();
  });

  it("搜索命中描述（名称不含关键词）", () => {
    renderSkills();

    fireEvent.change(screen.getByTestId("agents-search-skills"), {
      target: { value: "性能风险" },
    });
    expect(screen.queryByTestId("skill-card-s1")).toBeNull();
    expect(screen.getByTestId("skill-card-s2")).toBeInTheDocument();

    // 清除按钮复位。
    fireEvent.click(screen.getByTestId("agents-skills-search-clear"));
    expect(screen.getByTestId("skill-card-s1")).toBeInTheDocument();
  });

  it("「已安装(N)」计数控取全量（非筛选后）", () => {
    renderSkills();

    fireEvent.change(screen.getByTestId("agents-skills-category-filter"), {
      target: { value: "数据库" },
    });
    expect(screen.getByTestId("agents-skills-installed-count")).toHaveTextContent("已安装(3)");
  });

  it("启用开关为本地态：toggle 翻转 aria-checked（不落库）", () => {
    renderSkills();

    const toggle = screen.getByTestId("agents-skill-toggle-s1");
    expect(toggle).toHaveAttribute("role", "switch");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    // 本地演示提示随开关保留（sr-only）。
    expect(screen.getByTestId("skill-demo-hint-s1")).toBeInTheDocument();
  });
});

describe("SkillsTab · 非正常态", () => {
  it("真空态：统一空态面板 + CTA 打开受控添加弹窗；工具栏不渲染", () => {
    mockState.skills = [];
    const onAddOpenChange = renderSkills();

    expect(screen.getByTestId("agents-skills-empty")).toBeInTheDocument();
    expect(screen.getByText("还没有技能")).toBeInTheDocument();
    expect(screen.queryByTestId("agents-skills-toolbar")).toBeNull();

    fireEvent.click(screen.getByTestId("agents-skills-empty-create"));
    expect(onAddOpenChange).toHaveBeenCalledWith(true);
  });

  it("筛选后为空：提示 + 清除筛选", () => {
    renderSkills();

    fireEvent.change(screen.getByTestId("agents-search-skills"), { target: { value: "不存在" } });
    expect(screen.getByTestId("agents-skills-no-match")).toHaveTextContent("没有匹配的技能");

    fireEvent.click(screen.getByTestId("agents-skills-clear-filters"));
    expect(screen.getByTestId("skill-card-s1")).toBeInTheDocument();
    expect(screen.getByTestId("agents-search-skills")).toHaveValue("");
  });

  it("错误态优先于空态：面板含归一化 message，重试调用 refetch", () => {
    mockState.isError = true;
    mockState.error = new Error("skills down");
    renderSkills();

    const panel = screen.getByTestId("agents-skills-error");
    expect(panel).toHaveTextContent("加载失败");
    expect(panel).toHaveTextContent("skills down");
    expect(screen.queryByTestId("agents-skills-empty")).toBeNull();

    fireEvent.click(screen.getByTestId("agents-skills-retry"));
    expect(mockState.refetch).toHaveBeenCalledTimes(1);
  });
});

describe("SkillsTab · 受控弹窗", () => {
  it("添加技能弹窗受控：宿主置 addOpen=true 渲染，关闭回调 onAddOpenChange(false)", () => {
    const onAddOpenChange = renderSkills(true);

    expect(screen.getByTestId("agents-skills-add-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-add-dialog-empty")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("dialog-close"));
    expect(onAddOpenChange).toHaveBeenCalledWith(false);
  });

  it("上传技能弹窗（工具栏按钮）：提交仍禁用", () => {
    renderSkills();

    fireEvent.click(screen.getByTestId("agents-skills-upload"));
    expect(screen.getByTestId("agents-skills-upload-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-upload-input")).toBeInTheDocument();
    expect(screen.getByTestId("agents-skills-upload-submit")).toBeDisabled();
  });
});
