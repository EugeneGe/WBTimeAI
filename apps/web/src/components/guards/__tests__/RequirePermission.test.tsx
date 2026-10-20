// ---------------------------------------------------------------------------
// WBTimeAI · RequirePermission 单测（V0.4.7 · P1-4 / F1 + F4）
//
// 审计确认的真实缺陷：`fallback ?? <PermissionDenied/>` 会让 `fallback={null}`
// 被 `??` 判定为空值并**回退到默认占位**——即「显式不渲染」的调用点实际渲染了
// p-8 虚线占位块。改为 `fallback === undefined ? <PermissionDenied/> : fallback`
// 后语义为三态：`undefined` = 默认占位 / `null` = 显式不渲染 / 节点 = 自定义。
//
// 本文件三分支**互为对照**，且必须先有「正向控制组」（未传 fallback 时占位**存在**）。
// 若只断言 `queryByTestId("permission-denied")).toBeNull()`，锚点名打错也永远绿，
// 属循环论证——正向控制组是「null 断言真的能看见东西」的必要前提。
// ---------------------------------------------------------------------------
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";

/**
 * 渲染被测守卫。
 *
 * 说明：`RequirePermission` / `PermissionDenied` 仅依赖 `authStore`（权限）与
 * `i18nStore`（文案），**无** router / react-query 依赖，故无需包 `MemoryRouter`
 * 或 `QueryClientProvider`（多加无关 Provider 只会掩盖真实依赖面）。
 */
function renderGuard(ui: ReactElement): ReturnType<typeof render> {
  return render(ui);
}

describe("RequirePermission", () => {
  beforeEach(() => {
    // 无任何权限 → 守卫必走 fallback 分支。
    useAuthStore.setState({ permissions: [] });
    useI18nStore.setState({ language: "en" });
  });

  afterEach(() => {
    // 复位，避免污染其他测试文件（vitest 同进程复用 store）。
    useAuthStore.setState({ permissions: [] });
    useI18nStore.setState({ language: "en" });
  });

  it("未传 fallback → 渲染默认占位，且锚点携带权限码（正向控制组）", () => {
    renderGuard(
      <RequirePermission code="project:create">
        <span data-testid="guarded-child">secret</span>
      </RequirePermission>,
    );

    const placeholder = screen.getByTestId("permission-denied");
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toHaveAttribute("data-permission-code", "project:create");
    // 守卫生效：子节点不渲染。
    expect(screen.queryByTestId("guarded-child")).toBeNull();
  });

  it("fallback={null} → 显式不渲染任何占位（原 `??` 吞 null 缺陷的书面证据）", () => {
    renderGuard(
      <RequirePermission code="project:create" fallback={null}>
        <span data-testid="guarded-child">secret</span>
      </RequirePermission>,
    );

    // 同一份锚点、同一个查询方式：上一条能取到，这一条必须取不到。
    expect(screen.queryByTestId("permission-denied")).toBeNull();
    expect(screen.queryByTestId("guarded-child")).toBeNull();
  });

  it("自定义 fallback 节点 → 渲染该节点，且不叠加默认占位", () => {
    renderGuard(
      <RequirePermission
        code="project:create"
        fallback={<div data-testid="custom-denied">no way</div>}
      >
        <span data-testid="guarded-child">secret</span>
      </RequirePermission>,
    );

    expect(screen.getByTestId("custom-denied")).toBeInTheDocument();
    // 自定义分支**不得**同时渲染默认占位。
    expect(screen.queryByTestId("permission-denied")).toBeNull();
    expect(screen.queryByTestId("guarded-child")).toBeNull();
  });

  it("有权限 → children 正常渲染，无任何占位", () => {
    useAuthStore.setState({ permissions: ["project:create"] });

    renderGuard(
      <RequirePermission code="project:create">
        <span data-testid="guarded-child">secret</span>
      </RequirePermission>,
    );

    expect(screen.getByTestId("guarded-child")).toBeInTheDocument();
    expect(screen.queryByTestId("permission-denied")).toBeNull();
  });

  it("默认占位文案走 i18n（en 下为英文；回归守卫：原实现硬编码中文绕过 t()）", () => {
    renderGuard(
      <RequirePermission code="project:create">
        <span data-testid="guarded-child">secret</span>
      </RequirePermission>,
    );

    expect(screen.getByText("Missing permission: project:create")).toBeInTheDocument();
    expect(screen.queryByText("缺少权限：project:create")).toBeNull();
  });
});
