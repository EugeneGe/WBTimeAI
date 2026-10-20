// ---------------------------------------------------------------------------
// ErrorBoundary 演练用例（D-UI体验优化波 · WS-I · DU-9）
//
// 断言链（对齐 01 清单 §一「ErrorBoundary」验收点）：
//   1. 子组件抛错 → 兜底卡可见（**不白屏**）；
//   2. 点「重试」→ 重置边界状态并**恢复子树渲染**；
//   3. 正常子树直通渲染、不触发兜底。
//
// React 在捕获错误时会向 `console.error` 打日志，这里在用例内静音以免污染输出。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "@/components/common/ErrorBoundary";

/** 可切换的「炸弹」组件：`shouldThrow` 为真时在渲染期抛错。 */
let shouldThrow = true;

function Bomb() {
  if (shouldThrow) {
    throw new Error("演练：组件渲染抛错");
  }
  return <div data-testid="recovered">已恢复渲染</div>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    shouldThrow = true;
    // 静音 React 的错误日志（错误边界已将其转为兜底卡）。
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("子组件抛错时渲染兜底卡而非白屏", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId("error-boundary-fallback")).toBeInTheDocument();
    expect(screen.getByTestId("error-boundary-retry")).toBeInTheDocument();
    expect(screen.queryByTestId("recovered")).not.toBeInTheDocument();
  });

  it("点击「重试」重置边界并恢复子树渲染", () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-boundary-fallback")).toBeInTheDocument();

    // 修复根因后点重试 → 边界清空错误、子树重新挂载。
    shouldThrow = false;
    fireEvent.click(screen.getByTestId("error-boundary-retry"));

    expect(screen.getByTestId("recovered")).toBeInTheDocument();
    expect(screen.queryByTestId("error-boundary-fallback")).not.toBeInTheDocument();
  });

  it("正常子树直通渲染且不触发兜底", () => {
    shouldThrow = false;
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId("recovered")).toBeInTheDocument();
    expect(screen.queryByTestId("error-boundary-fallback")).not.toBeInTheDocument();
  });
});
