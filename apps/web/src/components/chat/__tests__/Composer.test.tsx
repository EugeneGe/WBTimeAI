// ---------------------------------------------------------------------------
// WBTimeAI · Composer 单测（D-UI 体验优化波 · WS-C / DU-6 + V0.4.5 B1 · WS-C1 + B3 · F-14）
//
// 覆盖交互态的关键路径：默认态 / ＋菜单二级联动（F-05a）/ 权限切换 /
// 专家位（经二级子菜单选中）/ 模型选择 / 配置自定义模型→`/models?add=1`（F-14.2 · D-UI5）/
// 输入框自适应（F-14.4）/ 移除三项（F-14.3）/ 发送 / `Ctrl+Enter` / streaming 取消。
//
// - 只读数据源（`useAgents` / `useSkills` / `useMcpServers` / `useModels.*`）以
//   `vi.mock` 打桩，避免网络；
// - 深链断言：`Composer` 现经 `useNavigate()` 跳 `/models?add=1`（D-UI5 收敛，
//   M03-03:104 / M07-01:147），故以 `MemoryRouter` 内的 `useLocation` 探针断言
//   **真实落点**（pathname + search），而非仅断言按钮存在；
// - 浮层为 WS-F 原语（`ui/dropdown-menu` + `ui/popover`，radix）→ 补最小 jsdom 桩。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Composer } from "@/components/chat/Composer";
import { en } from "@/i18n/locales/en";
import { useUiStore } from "@/stores/uiStore";

// --- jsdom 补丁：radix（dropdown-menu / popover / dialog / select / floating-ui）所需最小实现 ---
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
// jsdom 未实现 PointerEvent；radix 二级菜单依赖 `event.pointerType === "mouse"`
// 才展开，故补一个保留 `pointerType` 的 Polyfill（而非直接复用 MouseEvent）。
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

vi.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({
    data: [
      { id: "a1", name: "软件架构师" },
      { id: "a2", name: "数据分析专家" },
    ],
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useSkills", () => ({
  useSkills: () => ({
    data: [
      { id: "s1", name: "code-review", display_name: "代码审查" },
      { id: "s2", name: "summarize", display_name: "摘要" },
    ],
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useMcp", () => ({
  useMcpServers: () => ({
    data: [
      { id: "m1", name: "GitHub" },
      { id: "m2", name: "Postgres" },
    ],
    isLoading: false,
  }),
}));

// 模型供应商列表可切换（F-20.2 空态用例需注入空列表）。
const modelsSpy = vi.hoisted(() => ({
  providers: [
    { id: "p1", name: "WB-Time 中" },
    { id: "p2", name: "GLM-5.3-Flash" },
  ] as Array<{ id: string; name: string }>,
}));

vi.mock("@/hooks/useModels", () => ({
  useProviders: () => ({ data: modelsSpy.providers, isLoading: false }),
  useProviderModels: () => ({ data: [], isLoading: false }),
  useProviderModelsMany: () => [],
  useRegisterProvider: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRegisterModel: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSaveCredential: () => ({ mutateAsync: vi.fn(), mutate: vi.fn(), isPending: false }),
  useBindCredential: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCredentials: () => ({ data: [], isLoading: false }),
}));

interface HarnessProps {
  initialValue?: string;
  streaming?: boolean;
  initialAgentId?: string | null;
  onSend?: () => void;
  onCancel?: () => void;
  onAgentChange?: (id: string | null) => void;
}

/**
 * 路由探针：把当前 `pathname + search` 渲染到 `data-testid="location-probe"`。
 *
 * B-08 后「配置自定义模型」→ **就地打开设置·模型**（并直达添加表单），
 * 路由保持 `/`（不再导航到 `/models?add=1`）。
 */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

/** 受控测试壳：持有 value / agentId，转发回调。 */
function Harness({
  initialValue = "",
  streaming = false,
  initialAgentId = null,
  onSend,
  onCancel,
  onAgentChange,
}: HarnessProps) {
  const [value, setValue] = useState(initialValue);
  const [agentId, setAgentId] = useState<string | null>(initialAgentId);
  return (
    <MemoryRouter>
      <LocationProbe />
      <Composer
        value={value}
        onChange={setValue}
        onSend={onSend ?? (() => undefined)}
        streaming={streaming}
        onCancel={onCancel}
        agentId={agentId}
        onAgentChange={(id) => {
          setAgentId(id);
          onAgentChange?.(id);
        }}
      />
    </MemoryRouter>
  );
}

/** 打开 radix DropdownMenu（触发器响应 pointerdown）。 */
function openDropdown(trigger: HTMLElement): void {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
}

/** 鼠标悬停一级条目（radix 二级菜单经 pointermove 展开）。 */
function hoverItem(el: HTMLElement): void {
  fireEvent.pointerMove(el, { pointerType: "mouse" });
  fireEvent.pointerOver(el, { pointerType: "mouse" });
  fireEvent.mouseEnter(el, { pointerType: "mouse" });
}

describe("Composer", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // 复位模型供应商（F-20.2 空态用例会临时置空）。
    modelsSpy.providers = [
      { id: "p1", name: "WB-Time 中" },
      { id: "p2", name: "GLM-5.3-Flash" },
    ];
  });

  it("默认态：占位文案 + ＋／权限／模型／发送控件齐备；F-14.3 移除项不存在", () => {
    render(<Harness />);
    // 占位文案走 i18n（默认英文 `composer.placeholder`）。
    expect(screen.getByTestId("composer-input")).toHaveAttribute("placeholder", "Send a message…");
    expect(screen.getByTestId("composer-plus")).toBeInTheDocument();
    expect(screen.getByTestId("composer-permission")).toHaveTextContent(
      en["composer.permission.default"],
    );
    expect(screen.getByTestId("composer-model-trigger")).toHaveTextContent("WB-Time 中");
    // 空输入 → 发送禁用。
    expect(screen.getByTestId("composer-send")).toBeDisabled();
    // F-14.3：暂存提示词 / 上下文用量 / 增强提示词 三项已移除。
    expect(screen.queryByTestId("composer-stash")).not.toBeInTheDocument();
    expect(screen.queryByTestId("context-ring")).not.toBeInTheDocument();
    expect(screen.queryByTestId("composer-enhance")).not.toBeInTheDocument();
  });

  it("F-14.4：输入框两侧留白 + 内部右侧滚动（overflow-y-auto + 最大高度上限）", () => {
    render(<Harness />);
    const input = screen.getByTestId("composer-input");
    expect(input.className).toContain("overflow-y-auto");
    expect(input.className).toContain("px-2");
    expect(input.style.maxHeight).toBe("200px");
  });

  it("＋ 弹出：六项菜单（添加文件 / 引用对话中的文件 / 模式 / 专家 / 技能 / 连接器）", () => {
    render(<Harness />);
    openDropdown(screen.getByTestId("composer-plus"));
    expect(screen.getByTestId("composer-plus-menu")).toBeInTheDocument();
    for (const key of ["add-file", "ref-file", "mode", "expert", "skill", "connector"]) {
      expect(screen.getByTestId(`composer-plus-${key}`)).toBeInTheDocument();
    }
  });

  it("权限下拉：默认权限 → 完全访问", async () => {
    render(<Harness />);
    openDropdown(screen.getByTestId("composer-permission"));
    expect(screen.getByTestId("composer-permission-menu")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-permission-full"));
    await waitFor(() =>
      expect(screen.getByTestId("composer-permission")).toHaveTextContent(
        en["composer.permission.full"],
      ),
    );
  });

  it("F-05a 二级联动：悬停「专家」→ 右侧二级列表出现 → 点二级项父子菜单一并关闭并选中专家", async () => {
    const onAgentChange = vi.fn();
    render(<Harness onAgentChange={onAgentChange} />);

    openDropdown(screen.getByTestId("composer-plus"));
    expect(screen.getByTestId("composer-plus-menu")).toBeInTheDocument();
    // 初始专家位留空（无 chip）。
    expect(screen.queryByTestId("composer-expert-chip")).not.toBeInTheDocument();
    // 未悬停 → 二级面板尚未出现。
    expect(screen.queryByTestId("composer-plus-sub-expert")).not.toBeInTheDocument();

    // 悬停一级「专家」→ 二级子菜单出现。
    hoverItem(screen.getByTestId("composer-plus-expert"));
    const subPanel = await screen.findByTestId("composer-plus-sub-expert");
    expect(subPanel).toBeInTheDocument();
    expect(screen.getByTestId("composer-plus-sub-expert-item-a1")).toHaveTextContent("软件架构师");

    // 点击二级项 → 选中专家 + 一级 / 二级菜单一并关闭。
    fireEvent.click(screen.getByTestId("composer-plus-sub-expert-item-a1"));
    expect(onAgentChange).toHaveBeenCalledWith("a1");

    await waitFor(() => {
      expect(screen.queryByTestId("composer-plus-menu")).not.toBeInTheDocument();
      expect(screen.queryByTestId("composer-plus-sub-expert")).not.toBeInTheDocument();
    });

    // 选中后输入台显示专家 chip。
    const chip = await screen.findByTestId("composer-expert-chip");
    expect(chip).toHaveTextContent("软件架构师");
  });

  it("F-05a：技能 / 连接器 二级列表按数据源渲染", async () => {
    render(<Harness />);
    openDropdown(screen.getByTestId("composer-plus"));

    hoverItem(screen.getByTestId("composer-plus-skill"));
    const skillPanel = await screen.findByTestId("composer-plus-sub-skill");
    expect(skillPanel).toBeInTheDocument();
    expect(screen.getByTestId("composer-plus-sub-skill-item-s1")).toHaveTextContent("代码审查");

    hoverItem(screen.getByTestId("composer-plus-connector"));
    const connectorPanel = await screen.findByTestId("composer-plus-sub-connector");
    expect(connectorPanel).toBeInTheDocument();
    expect(screen.getByTestId("composer-plus-sub-connector-item-m1")).toHaveTextContent("GitHub");
  });

  it("B-08：模型「配置自定义模型」→ 就地打开设置·模型并直达添加表单（不再跳 /models）", async () => {
    render(<Harness />);
    // 初始停在根路由。
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/");

    fireEvent.click(screen.getByTestId("composer-model-trigger"));
    expect(await screen.findByTestId("composer-model-panel")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-model-configure"));

    // ① 设置弹窗就地打开，定位到「模型」分区。
    expect(await screen.findByTestId("settings-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("settings-dialog-nav-models")).toHaveAttribute(
      "aria-current",
      "page",
    );
    // ② 直达「添加模型配置」表单（autoOpenModelsAdd）。
    expect(await screen.findByTestId("add-model-config-dialog")).toBeInTheDocument();
    // ③ 路由不变（不再导航到 /models）。
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/");
  });

  it("Bug6c：语音按钮点击弹 toast 明示演示态", () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId("composer-voice"));
    // toast 经 uiStore.showToast（Toaster 订阅渲染）；此处直接断言 store 态（确定性）。
    // M02-03 #11：文案改走 i18n `composer.voice.demoToast`（默认语言 en）→ 断言取 en 字典。
    expect(useUiStore.getState().toast?.title).toBe(en["composer.voice.demoToast"]);
  });

  it("模型选择：切换选项后触发器更新（含配置自定义模型入口）", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId("composer-model-trigger"));
    expect(await screen.findByTestId("composer-model-panel")).toBeInTheDocument();
    expect(screen.getByTestId("composer-model-configure")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("composer-model-option-p2"));
    await waitFor(() =>
      expect(screen.getByTestId("composer-model-trigger")).toHaveTextContent("GLM-5.3-Flash"),
    );
  });

  it("F-20.3：外层卡片居中 + 适度最大宽（两侧留白）", () => {
    render(<Harness />);
    const composer = screen.getByTestId("composer");
    expect(composer.className).toContain("mx-auto");
    expect(composer.className).toContain("max-w-[768px]");
  });

  it("F-20.2：未配置模型（空列表）→ 空态引导（F-25.9 去重：无内嵌配置按钮），不再有兜底假档", async () => {
    modelsSpy.providers = [];
    render(<Harness />);
    fireEvent.click(screen.getByTestId("composer-model-trigger"));
    const empty = await screen.findByTestId("composer-model-empty");
    expect(empty).toHaveTextContent(en["composer.model.emptyGuide"]);
    // F-25.9：空态内不再渲染「配置自定义模型」按钮（收敛到底部唯一入口）。
    expect(screen.queryByTestId("composer-model-empty-configure")).toBeNull();
    expect(screen.getByTestId("composer-model-configure")).toBeInTheDocument();
    // F-20.2：兜底假档（FALLBACK_MODELS）已移除。
    expect(screen.queryByTestId("composer-model-option-wbtime-light")).toBeNull();
    expect(screen.queryByTestId("composer-model-option-p1")).toBeNull();
  });

  it("B-08：底部「去设置」→ 就地打开设置·模型并直达添加表单（路由不变）", async () => {
    modelsSpy.providers = [];
    render(<Harness />);
    fireEvent.click(screen.getByTestId("composer-model-trigger"));
    fireEvent.click(await screen.findByTestId("composer-model-configure"));

    expect(await screen.findByTestId("settings-dialog")).toBeInTheDocument();
    expect(await screen.findByTestId("add-model-config-dialog")).toBeInTheDocument();
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/");
  });

  it("发送：有内容时点击发送按钮触发 onSend", () => {
    const onSend = vi.fn();
    render(<Harness initialValue="你好" onSend={onSend} />);
    const send = screen.getByTestId("composer-send");
    expect(send).not.toBeDisabled();
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("Ctrl+Enter 快捷发送", () => {
    const onSend = vi.fn();
    render(<Harness initialValue="你好" onSend={onSend} />);
    fireEvent.keyDown(screen.getByTestId("composer-input"), { key: "Enter", ctrlKey: true });
    expect(onSend).toHaveBeenCalledTimes(1);
    // 普通 Enter 不发送（换行）。
    fireEvent.keyDown(screen.getByTestId("composer-input"), { key: "Enter" });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it("streaming 态显示取消并回调 onCancel", () => {
    const onCancel = vi.fn();
    render(<Harness streaming onCancel={onCancel} />);
    expect(screen.queryByTestId("composer-send")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
