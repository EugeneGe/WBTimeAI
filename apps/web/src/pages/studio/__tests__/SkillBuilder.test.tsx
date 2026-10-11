// ---------------------------------------------------------------------------
// Astra AI · SkillBuilder 单测（W3 / T2-18；W10 / T2-52 补强 · U-P2-17 / U-P2-30）
//
// 覆盖：
//   ① Skill 列表展示 + 新建（`skill:create`）；
//   ② 选中 Skill → 创建版本（DRAFT）+ 发布（`skill:update` / `skill:publish`）；
//   ③ 错误态（后端 409 → 渲染可见反馈，非静默）；
//   ④ `can()` 守卫：无 `skill:create` / `skill:update` / `skill:publish` 时动作不渲染。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { SkillBuilder } from "@/pages/studio/SkillBuilder";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** Skill 夹具（`SkillResponse`）。 */
const SKILL = {
  id: "s1",
  tenant_id: "t1",
  name: "demo",
  display_name: "Demo",
  description: null,
  category: "util",
  status: "DRAFT",
  current_version_id: null,
  current_version: null,
  created_by: "u1",
  created_at: null,
};

/** Skill 版本夹具（`SkillVersionResponse`）。 */
const SKILL_V1 = {
  id: "sv1",
  skill_id: "s1",
  version: "1.0.0",
  instructions: "",
  manifest: {},
  status: "DRAFT",
  created_by: "u1",
  created_at: null,
};

/** 新建版本返回值。 */
const SKILL_V2 = { ...SKILL_V1, id: "sv2", version: "1.0.1" };

/** 发布返回值（PUBLISHED）。 */
const SKILL_PUBLISHED = { ...SKILL_V1, status: "PUBLISHED" };

/** 渲染 SkillBuilder（独立 QueryClient；禁用重试）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SkillBuilder />
    </QueryClientProvider>,
  );
}

describe("SkillBuilder", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/skills", () => shell([SKILL])),
      http.get("/api/v1/skills/:skillId", () => shell(SKILL)),
      http.get("/api/v1/skills/:skillId/versions", () => shell([SKILL_V1])),
      http.post("/api/v1/skills", () => shell({ ...SKILL, id: "s2", name: "New" }, 201)),
      http.put("/api/v1/skills/:skillId", () => shell(SKILL)),
      http.post("/api/v1/skills/:skillId/versions", () => shell(SKILL_V2, 201)),
      http.post("/api/v1/skills/:skillId/publish", () => shell(SKILL_PUBLISHED)),
    );
  });

  it("展示 Skill 列表并可新建", async () => {
    renderPage();

    expect(await screen.findByTestId("skill-item-demo")).toHaveTextContent("Demo");

    fireEvent.change(screen.getByTestId("skill-name-input"), { target: { value: "New" } });
    fireEvent.click(screen.getByTestId("skill-create-submit"));

    expect(await screen.findByTestId("skill-feedback")).toHaveTextContent("Skill 已创建");
  });

  it("选中 Skill → 创建版本（DRAFT）+ 发布", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("skill-item-demo"));
    // 载入既有版本（1.0.0）。
    expect(await screen.findByText("1.0.0")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("skill-instructions-input"), {
      target: { value: "do things" },
    });
    fireEvent.click(screen.getByTestId("skill-version-submit"));
    expect(await screen.findByTestId("skill-feedback")).toHaveTextContent("版本已创建（DRAFT）");

    fireEvent.click(screen.getByTestId("skill-publish-submit"));
    expect(await screen.findByTestId("skill-feedback")).toHaveTextContent("已发布版本 1.0.0");
  });

  it("创建版本错误态：后端 409 → 渲染反馈（非静默）", async () => {
    server.use(
      http.post("/api/v1/skills/:skillId/versions", () =>
        HttpResponse.json(
          { code: "CONFLICT", message: "版本号已存在", data: {}, request_id: "t" },
          { status: 409 },
        ),
      ),
    );
    renderPage();

    fireEvent.click(await screen.findByTestId("skill-item-demo"));
    fireEvent.click(await screen.findByTestId("skill-version-submit"));

    // 错误路径渲染反馈（非静默）。
    // NOTE: 后端 `message` 文案当前被归一为「未知错误」（OBS-3 / 见验证报告）——
    //       本用例只断言「错误路径可见反馈」，不锁定文案；缺陷修复后另立文案断言。
    expect(await screen.findByTestId("skill-feedback")).not.toBeEmptyDOMElement();
  });

  it("can() 守卫：无 skill:create / skill:update / skill:publish 权限时动作不渲染", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();

    // 新建卡片受 `skill:create` 守护 → 被拦。
    expect(await screen.findByText("缺少权限：skill:create")).toBeInTheDocument();

    // 选中既有 Skill 后，编辑区 `skill:update`（保存元数据 + 创建版本）与 `skill:publish` 被拦。
    fireEvent.click(await screen.findByTestId("skill-item-demo"));
    const updateGuards = await screen.findAllByText("缺少权限：skill:update");
    expect(updateGuards.length).toBeGreaterThan(0);
    expect(screen.getByText("缺少权限：skill:publish")).toBeInTheDocument();
    // 动作按钮不渲染（仅占位提示）。
    expect(screen.queryByTestId("skill-version-submit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("skill-publish-submit")).not.toBeInTheDocument();
  });
});
