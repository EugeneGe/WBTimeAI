// ---------------------------------------------------------------------------
// WBTimeAI · KnowledgeManager 单测（W6 / T2-35 · U-P2-30；V0.4.6 · B-16 扩充）
//
// 覆盖：① H1 中文化（硬编码英文退场）；② 文档 `status` 索引进度；
//       ③ 新建弹窗（打开 / 校验 / 提交含描述）；④ 左空态 CTA + 右三步引导；
//       ⑤ 登记弹窗开与提交；⑥ 命中卡（score / 引用 / chunk_id）+ mode 徽标；
//       ⑦ 错误面板 + 重试（知识库 / 文档两份查询）；⑧ 聊天招呼语 chips 退场。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { KnowledgeManager } from "@/pages/studio/KnowledgeManager";
import { server } from "@/test/setup";
import { KNOWLEDGE_BASE } from "@/test/msw-handlers";
import { useAuthStore } from "@/stores/authStore";
import { useI18nStore } from "@/stores/i18nStore";

/** 渲染 Knowledge Manager（带独立 QueryClient；命中 msw 契约 handler）。 */
function renderManager() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <KnowledgeManager />
    </QueryClientProvider>,
  );
}

describe("KnowledgeManager", () => {
  beforeEach(() => {
    // 语言固定 zh-CN（产品默认中文界面；对齐 ExpertsTab.test 范式）。
    useI18nStore.setState({ language: "zh-CN" });
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("H1 中文化：知识库 + 副标题（「Knowledge Manager」硬编码退场）", async () => {
    renderManager();
    expect(await screen.findByRole("heading", { name: "知识库", level: 1 })).toBeInTheDocument();
    expect(
      screen.getByText("登记文档、跟踪索引进度，并试跑检索（语义 / 关键字自动回落）。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Knowledge Manager")).not.toBeInTheDocument();
  });

  it("展示文档 status 索引进度", async () => {
    renderManager();
    // 首个知识库自动选中 → 文档列表加载。
    expect(await screen.findByTestId("kb-item-Handbook")).toBeInTheDocument();
    expect(await screen.findByTestId("doc-status-guide.md")).toHaveTextContent("READY");
    expect(screen.getByTestId("doc-progress-guide.md")).toBeInTheDocument();
  });

  it("左列表项升级：图标块 + 名称 + 状态徽标（状态原样展示）", async () => {
    renderManager();
    const item = await screen.findByTestId("kb-item-Handbook");
    expect(item).toHaveTextContent("Handbook");
    expect(item).toHaveTextContent("ACTIVE");
  });

  it("新建弹窗：打开 → 空名校验 → 含描述提交成功并选中", async () => {
    renderManager();
    await screen.findByTestId("kb-item-Handbook");

    fireEvent.click(screen.getByTestId("kb-create-open"));
    const dialog = await screen.findByTestId("kb-create-dialog");
    expect(dialog).toBeInTheDocument();

    // 空名提交 → 就地校验错误，不发请求。
    fireEvent.click(screen.getByTestId("kb-create-submit"));
    expect(await screen.findByTestId("kb-create-error")).toHaveTextContent("请填写知识库名");

    // 含描述提交 → msw 默认 handler 回 KNOWLEDGE_BASE → 关弹窗 + 反馈 + 选中。
    fireEvent.change(screen.getByTestId("kb-name-input"), { target: { value: "产品手册" } });
    fireEvent.change(screen.getByTestId("kb-desc-input"), { target: { value: "产品文档与 FAQ" } });
    fireEvent.click(screen.getByTestId("kb-create-submit"));

    await waitFor(() => {
      expect(screen.queryByTestId("kb-create-dialog")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("knowledge-feedback")).toHaveTextContent("知识库已创建");
  });

  it("空库 → 左列仅「暂无知识库」占位，右侧留白、不再画三步引导（B-27）", async () => {
    server.use(http.get("/api/v1/knowledge/bases", () => shellList([])));
    renderManager();

    expect(await screen.findByTestId("kb-empty")).toBeInTheDocument();
    expect(screen.getByText("还没有知识库")).toBeInTheDocument();
    // 引导卡与其中的 STEP / CTA 全部退场（新建入口只剩卡头那一个）。
    expect(screen.queryByTestId("kb-empty-guide")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kb-empty-create")).not.toBeInTheDocument();
    expect(screen.queryByText("STEP 01")).not.toBeInTheDocument();
    expect(screen.queryByText("检索试跑")).not.toBeInTheDocument();
    // 卡头「新建」仍在且可用（空态不放重复 CTA）。
    expect(screen.getByTestId("kb-create-open")).toBeEnabled();
  });

  it("聊天招呼语 chips 全部退场（有数据态）", async () => {
    renderManager();
    await screen.findByTestId("kb-item-Handbook");
    // 缺省 chips 文案（chat.greeting.chip.*）不得出现在知识库页。
    expect(screen.queryByText("帮我把产品手册 v7 整理成 FAQ")).not.toBeInTheDocument();
    expect(screen.queryByText("检索知识库并总结要点")).not.toBeInTheDocument();
    expect(screen.queryByText("把 Q3 的表述改正式一点")).not.toBeInTheDocument();
  });

  it("文档表空 → EmptyState（暂无文档，无 chips）", async () => {
    server.use(http.get("/api/v1/knowledge/bases/:knowledgeBaseId/documents", () => shellList([])));
    renderManager();
    await screen.findByTestId("kb-item-Handbook");
    expect(await screen.findByText("暂无文档")).toBeInTheDocument();
    expect(screen.getByText("登记文档后，此处展示索引进度（2b 仅登记元数据）")).toBeInTheDocument();
    expect(screen.queryByText("检索知识库并总结要点")).not.toBeInTheDocument();
  });

  it("登记弹窗：打开 → 标题必填校验 → 提交成功反馈", async () => {
    renderManager();
    await screen.findByTestId("doc-status-guide.md");

    fireEvent.click(screen.getByTestId("doc-register-open"));
    const dialog = await screen.findByTestId("doc-register-dialog");
    expect(dialog).toHaveTextContent("2b 仅登记元数据");

    fireEvent.click(screen.getByTestId("doc-create-submit"));
    expect(await screen.findByTestId("doc-register-error")).toHaveTextContent("请填写文档标题");

    fireEvent.change(screen.getByTestId("doc-title-input"), { target: { value: "版本发布说明" } });
    fireEvent.click(screen.getByTestId("doc-create-submit"));

    await waitFor(() => {
      expect(screen.queryByTestId("doc-register-dialog")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("knowledge-feedback")).toHaveTextContent(
      "文档已登记（PENDING，等待索引）",
    );
  });

  it("检索试跑：命中卡（score 加粗 + 引用 + mono chunk_id）+ 关键字模式徽标", async () => {
    renderManager();
    await screen.findByTestId("kb-item-Handbook");

    fireEvent.change(screen.getByTestId("search-query-input"), { target: { value: "hello" } });
    fireEvent.click(screen.getByTestId("search-submit"));

    // 命中卡（score 加粗 / 引用可回溯 / chunk_id 展示）。
    const hit = await screen.findByTestId("search-hit-chk1");
    expect(hit).toHaveTextContent("Hello world");
    expect(screen.getByTestId("search-hit-score-chk1")).toHaveTextContent("score 0.420");
    expect(screen.getByTestId("search-hit-source-chk1")).toHaveTextContent("doc1");
    // 关键字路徽标（非语义检索；能力边界文案随 title 保留）。
    expect(screen.getByTestId("search-mode-badge")).toHaveTextContent("关键字模式");
  });

  it("知识库加载失败 → 卡内错误面板 + 重试恢复", async () => {
    server.use(
      http.get("/api/v1/knowledge/bases", () =>
        HttpResponse.json({ code: 500, message: "boom" }, { status: 500 }),
      ),
    );
    renderManager();

    const errorPanel = await screen.findByTestId("kb-error");
    expect(errorPanel).toBeInTheDocument();
    // 错误态右栏同样留白（无引导卡、无空态 CTA）。
    expect(screen.queryByTestId("kb-empty-guide")).not.toBeInTheDocument();

    // 重试 → 恢复默认成功 handler → 列表回来。
    server.use(http.get("/api/v1/knowledge/bases", () => shellList([KNOWLEDGE_BASE])));
    fireEvent.click(screen.getByTestId("kb-retry"));
    expect(await screen.findByTestId("kb-item-Handbook")).toBeInTheDocument();
    expect(screen.queryByTestId("kb-error")).not.toBeInTheDocument();
  });

  it("文档加载失败 → 文档卡内错误面板 + 重试", async () => {
    server.use(
      http.get("/api/v1/knowledge/bases/:knowledgeBaseId/documents", () =>
        HttpResponse.json({ code: 500, message: "boom" }, { status: 500 }),
      ),
    );
    renderManager();
    await screen.findByTestId("kb-item-Handbook");

    expect(await screen.findByTestId("docs-error")).toBeInTheDocument();
    server.use(
      http.get(
        "/api/v1/knowledge/bases/:knowledgeBaseId/documents",
        () => shellList([]), // 恢复成功（空列表）。
      ),
    );
    fireEvent.click(screen.getByTestId("docs-retry"));
    await waitFor(() => {
      expect(screen.queryByTestId("docs-error")).not.toBeInTheDocument();
    });
  });
});

/** 统一响应壳 JSON（测试内便捷封装）。 */
function shellList(data: unknown) {
  return HttpResponse.json(
    { code: 0, message: "ok", data, request_id: "test-request" },
    { status: 200 },
  );
}
