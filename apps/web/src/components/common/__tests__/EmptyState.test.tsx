// ---------------------------------------------------------------------------
// WBTimeAI · EmptyState 单测（B-01，V0.4.6 BugFix）
//
// 覆盖：
//   ① 缺省文案走 i18n：英文界面 = 英文招呼语（品牌 = `WBTimeAI`）+ 英文 chips；
//   ② 中文界面 = `你好，我是 观序智能平台 助理`（品牌随语言切换）；
//   ③ 语言切换即时重渲染（`useTranslation` 订阅）；
//   ④ 显式 `title` / `description` / `chips` props **优先**（既有签名兼容）。
// ---------------------------------------------------------------------------
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { EmptyState } from "@/components/common/EmptyState";
import { useI18nStore } from "@/stores/i18nStore";

describe("EmptyState · B-01 缺省文案随语言", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
  });

  it("英文界面：招呼语品牌 = WBTimeAI + 英文 chips", () => {
    render(<EmptyState />);

    expect(screen.getByTestId("empty-state")).toHaveTextContent("Hi, I'm the WBTimeAI assistant");
    expect(
      screen.getByTestId("empty-state-chip-Turn product manual v7 into an FAQ"),
    ).toBeInTheDocument();
    // 不应再出现中文品牌（旧硬编码）。
    expect(screen.queryByText(/观序智能平台/)).toBeNull();
  });

  it("中文界面：招呼语品牌 = 观序智能平台", () => {
    useI18nStore.setState({ language: "zh-CN" });
    render(<EmptyState />);

    expect(screen.getByTestId("empty-state")).toHaveTextContent("你好，我是 观序智能平台 助理");
    expect(screen.getByTestId("empty-state-description")).toHaveTextContent(
      "描述你的任务，或从下方场景快速开始",
    );
  });

  it("切换语言即时重渲染（无需重新挂载）", () => {
    render(<EmptyState />);
    expect(screen.getByTestId("empty-state")).toHaveTextContent("Hi, I'm the WBTimeAI assistant");

    act(() => {
      useI18nStore.getState().setLanguage("zh-CN");
    });

    expect(screen.getByTestId("empty-state")).toHaveTextContent("你好，我是 观序智能平台 助理");
  });

  it("显式 props 优先（自定义标题 / 描述 / chips 不被 i18n 覆盖）", () => {
    render(<EmptyState title="自定义标题" description="自定义描述" chips={["场景甲"]} />);

    expect(screen.getByText("自定义标题")).toBeInTheDocument();
    expect(screen.getByTestId("empty-state-description")).toHaveTextContent("自定义描述");
    expect(screen.getByTestId("empty-state-chip-场景甲")).toBeInTheDocument();
  });
});
