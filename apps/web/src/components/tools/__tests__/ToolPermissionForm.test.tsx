// ---------------------------------------------------------------------------
// WBTimeAI · ToolPermissionForm 单测（批 B · B10：`disabled` 透传）
//
// 覆盖：
//   ① 缺省（未传 `disabled`）→ 四下拉 / Scope 文本域 / 提交按钮均可交互（既有行为不回归）；
//   ② `disabled` → 四下拉 trigger 与 Scope 文本域均 `disabled`，提交按钮 disabled，
//      且点击提交**不会**发起授权请求（防御式短路）。
//
// - `useGrantToolPermission` 以 `vi.mock` 打桩（零网络、零 QueryClient）；
// - radix（select 浮层 / floating-ui）在 jsdom 下需补最小桩（对齐 Agents.test.tsx 范式）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ToolPermissionForm } from "@/components/tools/ToolPermissionForm";
import type { AgentResponse, ToolResponse } from "@/types";

/** 授权 mutation 打桩（hoisted：`vi.mock` 工厂内可见）。 */
const grantMutate = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useTools", () => ({
  useGrantToolPermission: () => ({ mutate: grantMutate, isPending: false }),
}));

// --- jsdom 补丁：radix（select / floating-ui）所需最小实现 ---
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
  window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
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

/** Agent 夹具。 */
const AGENTS: AgentResponse[] = [
  {
    id: "a1",
    name: "代码评审助手",
    type: "PRIMARY",
    status: "ACTIVE",
    created_by: "u1",
  },
];

/** Tool 夹具。 */
const TOOLS: ToolResponse[] = [
  {
    id: "t1",
    name: "read_file",
    display_name: "读取文件",
    description: "读取工作区文件",
    category: "fs",
    type: "BUILTIN",
    requires_sandbox: false,
    input_schema: {},
  },
];

/** 四个下拉 trigger 的 testid（与设计稿五维模型一一对应）。 */
const SELECT_TESTIDS = [
  "permission-agent-select",
  "permission-tool-select",
  "permission-action-select",
  "permission-effect-select",
] as const;

describe("ToolPermissionForm · 批 B · B10（disabled 透传）", () => {
  it("缺省不传 disabled：四下拉 / Scope / 提交按钮均可交互", () => {
    render(<ToolPermissionForm agents={AGENTS} tools={TOOLS} />);

    for (const testId of SELECT_TESTIDS) {
      expect(screen.getByTestId(testId)).toBeEnabled();
    }
    expect(screen.getByTestId("permission-scope-input")).toBeEnabled();
    expect(screen.getByTestId("permission-submit")).toBeEnabled();
  });

  it("disabled=true：四下拉 / Scope 不可交互，提交不发起请求", () => {
    grantMutate.mockClear();
    render(<ToolPermissionForm agents={AGENTS} tools={TOOLS} disabled />);

    // 四个下拉的 trigger（role=combobox）全部 disabled。
    for (const testId of SELECT_TESTIDS) {
      expect(screen.getByTestId(testId)).toBeDisabled();
    }

    // Scope 文本域 disabled（禁用态由 DOM 属性表达；fireEvent 绕过浏览器禁用拦截，
    // 故此处只断言 `disabled` 契约，不臆测键值是否变化）。
    const scope = screen.getByTestId("permission-scope-input");
    expect(scope).toBeDisabled();

    // 提交按钮 disabled，且点击不触发授权 mutation。
    const submit = screen.getByTestId("permission-submit");
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(grantMutate).not.toHaveBeenCalled();
  });
});

describe("ToolPermissionForm · 批 C-1 · M03-04（footerNote）", () => {
  it("传 footerNote → 卡底渲染说明（11px）", () => {
    const note = "已授权清单请到智能体详情核对；撤销能力当前未接线";
    render(<ToolPermissionForm agents={AGENTS} tools={TOOLS} footerNote={note} />);

    const footer = screen.getByTestId("tool-permission-footer-note");
    expect(footer).toBeInTheDocument();
    expect(footer).toHaveTextContent(note);
    expect(footer).toHaveClass("text-[11px]");
  });

  it("不传 footerNote → 无卡底说明（智能体详情页保持无页脚）", () => {
    render(<ToolPermissionForm agents={AGENTS} tools={TOOLS} />);

    expect(screen.queryByTestId("tool-permission-footer-note")).not.toBeInTheDocument();
  });
});
