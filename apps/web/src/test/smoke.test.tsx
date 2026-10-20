// ---------------------------------------------------------------------------
// WBTimeAI · 前端冒烟单测（T1-01 / P0-09）
//
// 两条必绿断言：
//   1. 渲染一个 React 组件并由 jest-dom 断言可见（RTL 生效）；
//   2. 发起一次 `/api/v1/health` 请求，由 msw 拦截并返回统一响应壳（msw 生效）。
//
// 目的：为 `pnpm --filter @wbtime-ai/web test` 提供最小可行、稳定不 flaky 的基线，
// 使 CI 前端测试门禁「有 ≥1 条必绿」。
// ---------------------------------------------------------------------------
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function Greeting() {
  return <h1>WBTimeAI Frontend Smoke</h1>;
}

describe("frontend smoke", () => {
  it("renders a component via React Testing Library", () => {
    render(<Greeting />);
    expect(screen.getByRole("heading", { name: "WBTimeAI Frontend Smoke" })).toBeInTheDocument();
  });

  it("resolves an msw-mocked /api/v1 request", async () => {
    const response = await fetch("/api/v1/health");
    expect(response.status).toBe(200);

    const body = (await response.json()) as {
      code: number;
      message: string;
      data: { status: string };
    };
    expect(body).toEqual({ code: 0, message: "ok", data: { status: "ok" } });
  });
});
