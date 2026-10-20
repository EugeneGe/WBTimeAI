// ---------------------------------------------------------------------------
// WBTimeAI · DocumentTitle 单测（B-01，V0.4.6 BugFix）
//
// 覆盖：
//   ① 英文 → `document.title === "WBTimeAI"`；
//   ② zh-CN → `document.title === "观序智能平台"`；
//   ③ 运行中切换语言 → 标题跟随（`useTranslation` + `useEffect`）；
//   ④ 组件不渲染任何 DOM 节点（返回 `null`）。
// ---------------------------------------------------------------------------
import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { DocumentTitle } from "@/components/common/DocumentTitle";
import { useI18nStore } from "@/stores/i18nStore";

describe("DocumentTitle · B-01 标题随语言", () => {
  beforeEach(() => {
    useI18nStore.setState({ language: "en" });
    document.title = "stale";
  });

  it("英文：document.title = WBTimeAI", () => {
    render(<DocumentTitle />);

    expect(document.title).toBe("WBTimeAI");
  });

  it("中文：document.title = 观序智能平台", () => {
    useI18nStore.setState({ language: "zh-CN" });
    render(<DocumentTitle />);

    expect(document.title).toBe("观序智能平台");
  });

  it("切换语言：标题即时跟随", () => {
    render(<DocumentTitle />);
    expect(document.title).toBe("WBTimeAI");

    act(() => {
      useI18nStore.getState().setLanguage("zh-CN");
    });
    expect(document.title).toBe("观序智能平台");

    act(() => {
      useI18nStore.getState().setLanguage("en");
    });
    expect(document.title).toBe("WBTimeAI");
  });

  it("零 DOM 节点（仅副作用）", () => {
    const { container } = render(<DocumentTitle />);

    expect(container).toBeEmptyDOMElement();
  });
});
