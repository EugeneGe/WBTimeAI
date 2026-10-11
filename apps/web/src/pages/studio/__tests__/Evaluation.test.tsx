// ---------------------------------------------------------------------------
// Astra AI · Evaluation 单测（W9 / T2-47 · U-P2-*）
//
// 覆盖：
//   ① 数据集列表展示 + 新建；
//   ② 查看用例 + 追加用例 + 发布（PUBLISHED）；
//   ③ 启动 Evaluation Run 并展示逐 case 分数；
//   ④ 两版本对比展示，**缺失指标渲染 N/A（不得视为 0）**；
//   ⑤ `can()` / `RequirePermission` 守卫（无权限时 `evaluation:write` / `evaluation:run` 被拦）。
//
// 以 msw 打桩后端契约（逐字对齐冻结 DTO：snake_case + 统一响应壳）。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { Evaluation } from "@/pages/studio/Evaluation";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** 数据集夹具（`DatasetOut`）。 */
const DATASET = {
  id: "ds1",
  name: "Smoke",
  version: 1,
  parent_dataset_id: null,
  status: "DRAFT",
  description: null,
  created_by: "u1",
  workspace_id: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
};

/** 用例夹具（`CaseOut`）。 */
const CASE = {
  id: "case1",
  dataset_id: "ds1",
  case_key: "q1",
  input: { q: "2+2" },
  expected: { a: 4 },
  assertions: [],
  tags: null,
  position: 0,
};

/** 追加用例返回值（`POST .../cases`）。 */
const CASE_2 = { ...CASE, id: "case2", case_key: "q2", input: { q: "3+3" } };

/** 评测运行夹具（`RunOut`）。 */
const RUN = {
  id: "run1",
  dataset_id: "ds1",
  agent_id: "a1",
  agent_version_id: "v1",
  status: "SUCCESS",
  idempotency_key: null,
  started_at: null,
  completed_at: null,
  summary: null,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
};

/** 逐例结果夹具（`ResultOut`）。 */
const RESULT = {
  id: "res1",
  evaluation_run_id: "run1",
  case_id: "case1",
  agent_run_id: "ar1",
  status: "SUCCESS",
  score: 1,
  assertion_results: [{ scorer: "exact_match", passed: true, weight: 1, score: 1, detail: null }],
  duration_ms: 120,
  token_usage: { prompt: 10, completion: 5 },
  cost: 0.001,
  error_type: null,
};

/** 回归对比报告夹具（`CompareReport`）——`cost` 缺失 → `N/A`。 */
const COMPARE = {
  dataset_id: "ds1",
  dataset_version: 1,
  agent_version_a: "v1",
  agent_version_b: "v2",
  pass_rate: { a: 1, b: 0.5, delta: -0.5 },
  mean_score: { a: 0.9, b: 0.8, delta: -0.1 },
  fails: { only_a: [], only_b: ["q2"], both: [] },
  duration_ms: { a: 120, b: 130, delta: 10 },
  token_usage: { a: 100, b: 120, delta: 20 },
  // 🔴 缺失指标 → 页面渲染 `N/A`（不得视为 0）。
  cost: { a: null, b: null, delta: null },
};

/** 渲染 Evaluation（独立 QueryClient）。 */
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Evaluation />
    </QueryClientProvider>,
  );
}

describe("Evaluation", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });

    server.use(
      http.get("/api/v1/evaluation/datasets", () => shell({ items: [DATASET] })),
      http.post("/api/v1/evaluation/datasets", () =>
        shell({ ...DATASET, id: "ds2", name: "New Set" }, 201),
      ),
      http.get("/api/v1/evaluation/datasets/:datasetId", () =>
        shell({ dataset: DATASET, cases: [CASE] }),
      ),
      http.post("/api/v1/evaluation/datasets/:datasetId/cases", () => shell(CASE_2, 201)),
      http.post("/api/v1/evaluation/datasets/:datasetId/publish", () =>
        shell({ ...DATASET, status: "PUBLISHED" }),
      ),
      http.post("/api/v1/evaluation/runs", () => shell(RUN, 201)),
      http.get("/api/v1/evaluation/runs/:runId", () => shell({ run: RUN, results: [RESULT] })),
      http.get("/api/v1/evaluation/runs/:runId/compare", () => shell(COMPARE)),
    );
  });

  it("展示数据集列表并可新建", async () => {
    renderPage();

    expect(await screen.findByTestId("dataset-row-ds1")).toHaveTextContent("Smoke");

    fireEvent.change(screen.getByTestId("dataset-name-input"), { target: { value: "New Set" } });
    fireEvent.click(screen.getByTestId("dataset-create-button"));

    expect(await screen.findByTestId("evaluation-feedback")).toHaveTextContent(
      "已新建数据集 New Set",
    );
  });

  it("查看用例、追加用例并发布", async () => {
    renderPage();

    fireEvent.click(await screen.findByTestId("dataset-select-ds1"));
    expect(await screen.findByTestId("case-row-q1")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("case-key-input"), { target: { value: "q2" } });
    fireEvent.change(screen.getByTestId("case-input"), { target: { value: '{"q":"3+3"}' } });
    fireEvent.click(screen.getByTestId("case-add-button"));
    expect(await screen.findByTestId("evaluation-feedback")).toHaveTextContent("已追加用例 q2");

    fireEvent.click(screen.getByTestId("dataset-publish-button"));
    expect(await screen.findByTestId("evaluation-feedback")).toHaveTextContent(
      "已发布数据集 Smoke",
    );
  });

  it("启动评测运行并展示逐 case 分数", async () => {
    renderPage();

    // 等待数据集加载，确保 select 含目标 option（否则 change 无法生效）。
    await screen.findByTestId("dataset-row-ds1");
    fireEvent.change(screen.getByTestId("run-dataset-select"), { target: { value: "ds1" } });
    fireEvent.change(screen.getByTestId("run-agent-input"), { target: { value: "a1" } });
    fireEvent.change(screen.getByTestId("run-agent-version-input"), { target: { value: "v1" } });
    fireEvent.click(screen.getByTestId("run-start-button"));

    expect(await screen.findByTestId("run-status")).toHaveTextContent("SUCCESS");
    expect(await screen.findByTestId("run-result-score-case1")).toHaveTextContent("1");
  });

  it("对比展示通过率 / 失败 case，缺失指标渲染 N/A", async () => {
    renderPage();

    fireEvent.change(screen.getByTestId("compare-run-input"), { target: { value: "run1" } });
    fireEvent.change(screen.getByTestId("compare-baseline-input"), { target: { value: "run0" } });
    fireEvent.click(screen.getByTestId("compare-button"));

    expect(await screen.findByTestId("compare-report")).toBeInTheDocument();
    // 有值指标正常展示。
    expect(screen.getByTestId("compare-pass-rate-a")).toHaveTextContent("1");
    expect(screen.getByTestId("compare-pass-rate-delta")).toHaveTextContent("-0.5");
    // 失败 case 分组。
    expect(screen.getByTestId("compare-fails-only-b")).toHaveTextContent("q2");
    // 🔴 缺失指标 → `N/A`（不得视为 0）。
    expect(screen.getByTestId("compare-cost-a")).toHaveTextContent("N/A");
    expect(screen.getByTestId("compare-cost-b")).toHaveTextContent("N/A");
    expect(screen.getByTestId("compare-cost-delta")).toHaveTextContent("N/A");
  });

  it("can() 守卫：无 evaluation:write / evaluation:run 权限被拦", async () => {
    useAuthStore.setState({ permissions: [] });
    renderPage();

    expect(await screen.findByText("缺少权限：evaluation:write")).toBeInTheDocument();
    expect(screen.getByText("缺少权限：evaluation:run")).toBeInTheDocument();
  });
});
