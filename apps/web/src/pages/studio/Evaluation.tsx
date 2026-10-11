import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toApiError } from "@/lib/api";
import { usePermission } from "@/lib/permission";
import { evaluationService } from "@/services/evaluation";
import { useAuthStore } from "@/stores/authStore";
import type {
  CompareReport,
  DatasetOut,
  MetricTriple,
  RunOut,
  RunStatus,
  ResultOut,
} from "@/types";

/** Evaluation 本地 query key 工厂（页内持有，不改 `lib/query.ts`）。 */
const evaluationKeys = {
  datasets: ["evaluation", "datasets"] as const,
  dataset: (id: string) => ["evaluation", "dataset", id] as const,
  run: (id: string) => ["evaluation", "run", id] as const,
};

/**
 * 提取可展示的错误消息。
 *
 * 🔴 `@/lib/api` 拦截器**已**把错误归一化为 `ApiError`（含 `message`）——优先读 `message`；
 *    仅当收到非归一化错误（无 `message`）时回退 {@link toApiError}。
 */
function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return toApiError(error).message;
}

/**
 * 格式化单个指标值。
 *
 * 🔴 §5.5：缺失指标（`null` / `undefined`）一律渲染 `N/A`，**不得视为 0**。
 */
function formatMetric(value: number | null | undefined): string {
  return value === null || value === undefined ? "N/A" : String(value);
}

/** 解析 JSON 文本（用例 `input` / `expected`）；失败返回错误信息。 */
function parseJsonSafe(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, error: "需为合法 JSON" };
  }
}

/** 运行状态徽章配色（`SUCCESS` 主色 / `FAILED` 危险 / 其余次要）。 */
function runStatusVariant(status: RunStatus): "default" | "secondary" | "destructive" | "outline" {
  if (status === "SUCCESS") {
    return "default";
  }
  if (status === "FAILED") {
    return "destructive";
  }
  return "secondary";
}

/** 指标三元组单元格（A / B / Δ）。 */
function MetricCells({ metricKey, triple }: { metricKey: string; triple: MetricTriple }) {
  return (
    <>
      <TableCell data-testid={`compare-${metricKey}-a`}>{formatMetric(triple.a)}</TableCell>
      <TableCell data-testid={`compare-${metricKey}-b`}>{formatMetric(triple.b)}</TableCell>
      <TableCell data-testid={`compare-${metricKey}-delta`}>{formatMetric(triple.delta)}</TableCell>
    </>
  );
}

/** 对比报告区块（通过率 / 平均分 / 失败 case / 耗时 / Token / 成本 + Δ；缺失 `N/A`）。 */
function CompareReportView({ report }: { report: CompareReport }) {
  return (
    <div className="space-y-3" data-testid="compare-report">
      <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">数据集版本</span>
          <span data-testid="compare-dataset-version">{report.dataset_version}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">A / B Agent 版本</span>
          <span className="font-mono" data-testid="compare-agent-versions">
            {report.agent_version_a} / {report.agent_version_b}
          </span>
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>指标</TableHead>
            <TableHead>A（baseline）</TableHead>
            <TableHead>B（当前）</TableHead>
            <TableHead>Δ</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>通过率</TableCell>
            <MetricCells metricKey="pass-rate" triple={report.pass_rate} />
          </TableRow>
          <TableRow>
            <TableCell>平均分</TableCell>
            <MetricCells metricKey="mean-score" triple={report.mean_score} />
          </TableRow>
          <TableRow>
            <TableCell>平均耗时 (ms)</TableCell>
            <MetricCells metricKey="duration-ms" triple={report.duration_ms} />
          </TableRow>
          <TableRow>
            <TableCell>平均 Token</TableCell>
            <MetricCells metricKey="token-usage" triple={report.token_usage} />
          </TableRow>
          <TableRow>
            <TableCell>平均成本</TableCell>
            <MetricCells metricKey="cost" triple={report.cost} />
          </TableRow>
        </TableBody>
      </Table>

      <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        <div className="rounded-md border p-2">
          <div className="mb-1 text-muted-foreground">仅 A 失败</div>
          <div data-testid="compare-fails-only-a">
            {report.fails.only_a.length > 0 ? report.fails.only_a.join(", ") : "无"}
          </div>
        </div>
        <div className="rounded-md border p-2">
          <div className="mb-1 text-muted-foreground">仅 B 失败</div>
          <div data-testid="compare-fails-only-b">
            {report.fails.only_b.length > 0 ? report.fails.only_b.join(", ") : "无"}
          </div>
        </div>
        <div className="rounded-md border p-2">
          <div className="mb-1 text-muted-foreground">两者失败</div>
          <div data-testid="compare-fails-both">
            {report.fails.both.length > 0 ? report.fails.both.join(", ") : "无"}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 运行结果视图（Run 状态 + 逐 case 分数 / 断言）。 */
function RunResultView({ run, results }: { run: RunOut; results: ResultOut[] }) {
  return (
    <div className="space-y-3" data-testid="run-detail">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">运行状态</span>
        <Badge variant={runStatusVariant(run.status)} data-testid="run-status">
          {run.status}
        </Badge>
        <span className="font-mono text-xs text-muted-foreground" data-testid="run-id">
          {run.id}
        </span>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>用例</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>分数</TableHead>
            <TableHead>耗时 (ms)</TableHead>
            <TableHead>错误</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {results.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground" data-testid="run-no-results">
                暂无结果
              </TableCell>
            </TableRow>
          ) : (
            results.map((result) => (
              <TableRow key={result.id} data-testid={`run-result-${result.case_id}`}>
                <TableCell className="font-mono text-xs">{result.case_id}</TableCell>
                <TableCell>
                  <Badge variant={result.status === "SUCCESS" ? "secondary" : "destructive"}>
                    {result.status}
                  </Badge>
                </TableCell>
                <TableCell data-testid={`run-result-score-${result.case_id}`}>
                  {formatMetric(result.score)}
                </TableCell>
                <TableCell>{formatMetric(result.duration_ms)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {result.error_type ?? "—"}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Evaluation（W9 / T2-47；设计 §2.13.2；裁定 §2.3 / §5.5 / R11）。
 *
 * 三区：
 * ① **任务集管理**——数据集列表 / 新建 / 查看用例 / 追加用例 / 发布（`PUBLISHED`）；
 * ② **批量执行**——选 dataset + agent + agent_version 启动 Run（**幂等**），展示 Run 状态与
 *    逐 case 分数 / 断言结果；
 * ③ **回归对比**——给定当前 Run 与 baseline Run，展示通过率 / 平均分 / 失败 case / 耗时 /
 *    Token / 成本及 Δ；**缺失指标渲染 `N/A`（不得视为 0）**。
 *
 * 🔴 权限守卫（冻结码）：读取 `evaluation:read`、写入 `evaluation:write`、执行 `evaluation:run`
 *    ——动作按钮经 {@link RequirePermission}（`can()`）守护；无权限时展示「缺少权限：<code>」。
 */
export function Evaluation() {
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const { can } = usePermission();

  const [feedback, setFeedback] = useState<string | null>(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [compareReport, setCompareReport] = useState<CompareReport | null>(null);

  // 新建数据集表单。
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");

  // 追加用例表单。
  const [caseKey, setCaseKey] = useState("");
  const [caseInput, setCaseInput] = useState("");
  const [caseExpected, setCaseExpected] = useState("");

  // 批量执行表单。
  const [runDatasetId, setRunDatasetId] = useState("");
  const [runAgentId, setRunAgentId] = useState("");
  const [runAgentVersionId, setRunAgentVersionId] = useState("");
  const [runIdempotencyKey, setRunIdempotencyKey] = useState("");

  // 回归对比表单。
  const [compareRunId, setCompareRunId] = useState("");
  const [compareBaselineId, setCompareBaselineId] = useState("");

  const datasetsQuery = useQuery({
    queryKey: evaluationKeys.datasets,
    queryFn: () => evaluationService.listDatasets(),
    enabled: isAuthenticated,
  });

  const datasetDetailQuery = useQuery({
    queryKey: evaluationKeys.dataset(selectedDatasetId ?? ""),
    queryFn: () => evaluationService.getDataset(selectedDatasetId as string),
    enabled: Boolean(selectedDatasetId),
  });

  const runDetailQuery = useQuery({
    queryKey: evaluationKeys.run(selectedRunId ?? ""),
    queryFn: () => evaluationService.getRun(selectedRunId as string),
    enabled: Boolean(selectedRunId),
  });

  const createDataset = useMutation({
    mutationFn: (payload: { name: string; description: string }) =>
      evaluationService.createDataset({
        name: payload.name,
        description: payload.description.length > 0 ? payload.description : null,
      }),
    onSuccess: (dataset) => {
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.datasets });
      setSelectedDatasetId(dataset.id);
      setNewName("");
      setNewDescription("");
      setFeedback(`已新建数据集 ${dataset.name}`);
    },
    onError: (error) => setFeedback(resolveErrorMessage(error)),
  });

  const addCase = useMutation({
    mutationFn: (payload: {
      datasetId: string;
      caseKey: string;
      input: unknown;
      expected: unknown;
    }) =>
      evaluationService.addCase(payload.datasetId, {
        case_key: payload.caseKey,
        input: payload.input,
        expected: payload.expected,
        assertions: [],
        tags: null,
        position: 0,
      }),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({
        queryKey: evaluationKeys.dataset(created.dataset_id),
      });
      setCaseKey("");
      setCaseInput("");
      setCaseExpected("");
      setFeedback(`已追加用例 ${created.case_key}`);
    },
    onError: (error) => setFeedback(resolveErrorMessage(error)),
  });

  const publishDataset = useMutation({
    mutationFn: (datasetId: string) => evaluationService.publishDataset(datasetId),
    onSuccess: (dataset) => {
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.datasets });
      void queryClient.invalidateQueries({ queryKey: evaluationKeys.dataset(dataset.id) });
      setFeedback(`已发布数据集 ${dataset.name}（${dataset.status}）`);
    },
    onError: (error) => setFeedback(resolveErrorMessage(error)),
  });

  const startRun = useMutation({
    mutationFn: (payload: {
      datasetId: string;
      agentId: string;
      agentVersionId: string;
      idempotencyKey: string;
    }) =>
      evaluationService.startRun({
        dataset_id: payload.datasetId,
        agent_id: payload.agentId,
        agent_version_id: payload.agentVersionId,
        idempotency_key: payload.idempotencyKey.length > 0 ? payload.idempotencyKey : null,
      }),
    onSuccess: (run) => {
      setSelectedRunId(run.id);
      setCompareRunId(run.id);
      setFeedback(`已启动评测运行 ${run.id}（${run.status}）`);
    },
    onError: (error) => setFeedback(resolveErrorMessage(error)),
  });

  const compare = useMutation({
    mutationFn: (payload: { runId: string; baselineRunId: string }) =>
      evaluationService.compare(payload.runId, payload.baselineRunId),
    onSuccess: (report) => {
      setCompareReport(report);
      setFeedback("对比完成");
    },
    onError: (error) => setFeedback(resolveErrorMessage(error)),
  });

  const datasets: DatasetOut[] = datasetsQuery.data?.items ?? [];
  const detail = datasetDetailQuery.data;
  const runDetail = runDetailQuery.data;

  const handleSelectDataset = (dataset: DatasetOut): void => {
    setSelectedDatasetId(dataset.id);
    setRunDatasetId(dataset.id);
    setFeedback(null);
  };

  const handleCreateDataset = (): void => {
    if (!newName.trim()) {
      setFeedback("请填写数据集名称");
      return;
    }
    createDataset.mutate({ name: newName.trim(), description: newDescription.trim() });
  };

  const handleAddCase = (): void => {
    if (!selectedDatasetId) {
      setFeedback("请先选择数据集");
      return;
    }
    if (!caseKey.trim()) {
      setFeedback("请填写用例 key");
      return;
    }
    const inputParsed = parseJsonSafe(caseInput.trim() || "null");
    if (!inputParsed.ok) {
      setFeedback(`用例 input ${inputParsed.error}`);
      return;
    }
    let expected: unknown = null;
    if (caseExpected.trim().length > 0) {
      const expectedParsed = parseJsonSafe(caseExpected.trim());
      if (!expectedParsed.ok) {
        setFeedback(`用例 expected ${expectedParsed.error}`);
        return;
      }
      expected = expectedParsed.value;
    }
    addCase.mutate({
      datasetId: selectedDatasetId,
      caseKey: caseKey.trim(),
      input: inputParsed.value,
      expected,
    });
  };

  const handlePublish = (): void => {
    if (!selectedDatasetId) {
      setFeedback("请先选择数据集");
      return;
    }
    publishDataset.mutate(selectedDatasetId);
  };

  const handleStartRun = (): void => {
    if (!runDatasetId.trim() || !runAgentId.trim() || !runAgentVersionId.trim()) {
      setFeedback("请填写 dataset / agent / agent_version");
      return;
    }
    startRun.mutate({
      datasetId: runDatasetId.trim(),
      agentId: runAgentId.trim(),
      agentVersionId: runAgentVersionId.trim(),
      idempotencyKey: runIdempotencyKey.trim(),
    });
  };

  const handleCompare = (): void => {
    if (!compareRunId.trim() || !compareBaselineId.trim()) {
      setFeedback("请填写当前 Run 与 baseline Run");
      return;
    }
    compare.mutate({ runId: compareRunId.trim(), baselineRunId: compareBaselineId.trim() });
  };

  return (
    <div className="space-y-4" data-testid="evaluation">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Evaluation</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="evaluation-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      {!can("evaluation:read") ? (
        <div
          className="rounded-md border border-dashed p-2 text-xs text-muted-foreground"
          data-testid="evaluation-read-denied"
        >
          缺少权限：evaluation:read
        </div>
      ) : null}

      {/* ① 任务集管理 */}
      <Card>
        <CardHeader>
          <CardTitle>任务集管理</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>版本</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {datasetsQuery.isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : datasets.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground"
                    data-testid="datasets-empty"
                  >
                    暂无数据集
                  </TableCell>
                </TableRow>
              ) : (
                datasets.map((dataset) => (
                  <TableRow key={dataset.id} data-testid={`dataset-row-${dataset.id}`}>
                    <TableCell>{dataset.name}</TableCell>
                    <TableCell>{dataset.version}</TableCell>
                    <TableCell>
                      <Badge variant={dataset.status === "PUBLISHED" ? "default" : "secondary"}>
                        {dataset.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        data-testid={`dataset-select-${dataset.id}`}
                        onClick={() => handleSelectDataset(dataset)}
                      >
                        查看用例
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="dataset-name">名称</Label>
              <Input
                id="dataset-name"
                data-testid="dataset-name-input"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="dataset-description">描述</Label>
              <Input
                id="dataset-description"
                data-testid="dataset-description-input"
                value={newDescription}
                onChange={(event) => setNewDescription(event.target.value)}
              />
            </div>
            <div className="flex items-end">
              <RequirePermission code="evaluation:write">
                <Button
                  size="sm"
                  data-testid="dataset-create-button"
                  onClick={handleCreateDataset}
                  disabled={createDataset.isPending}
                >
                  新建数据集
                </Button>
              </RequirePermission>
            </div>
          </div>

          {detail ? (
            <div className="space-y-3 rounded-md border p-3" data-testid="dataset-detail">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {detail.dataset.name} v{detail.dataset.version}
                </span>
                <span className="text-xs text-muted-foreground" data-testid="dataset-detail-status">
                  {detail.dataset.status}
                </span>
              </div>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>用例 key</TableHead>
                    <TableHead>输入</TableHead>
                    <TableHead>期望</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.cases.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={3}
                        className="text-muted-foreground"
                        data-testid="dataset-cases-empty"
                      >
                        暂无用例
                      </TableCell>
                    </TableRow>
                  ) : (
                    detail.cases.map((item) => (
                      <TableRow key={item.id} data-testid={`case-row-${item.case_key}`}>
                        <TableCell className="font-mono text-xs">{item.case_key}</TableCell>
                        <TableCell className="max-w-xs truncate font-mono text-xs">
                          {JSON.stringify(item.input)}
                        </TableCell>
                        <TableCell className="max-w-xs truncate font-mono text-xs">
                          {item.expected === null ? "—" : JSON.stringify(item.expected)}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                <div className="space-y-2">
                  <Label htmlFor="case-key">用例 key</Label>
                  <Input
                    id="case-key"
                    data-testid="case-key-input"
                    value={caseKey}
                    onChange={(event) => setCaseKey(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="case-input">输入 (JSON)</Label>
                  <Input
                    id="case-input"
                    data-testid="case-input"
                    value={caseInput}
                    onChange={(event) => setCaseInput(event.target.value)}
                    placeholder='{"q": "2+2"}'
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="case-expected">期望 (JSON，可选)</Label>
                  <Input
                    id="case-expected"
                    data-testid="case-expected-input"
                    value={caseExpected}
                    onChange={(event) => setCaseExpected(event.target.value)}
                  />
                </div>
                <div className="flex items-end">
                  <RequirePermission code="evaluation:write">
                    <Button
                      size="sm"
                      data-testid="case-add-button"
                      onClick={handleAddCase}
                      disabled={addCase.isPending}
                    >
                      追加用例
                    </Button>
                  </RequirePermission>
                </div>
              </div>

              <RequirePermission code="evaluation:write">
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="dataset-publish-button"
                  onClick={handlePublish}
                  disabled={publishDataset.isPending || detail.dataset.status === "PUBLISHED"}
                >
                  发布
                </Button>
              </RequirePermission>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ② 批量执行 */}
      <Card>
        <CardHeader>
          <CardTitle>批量执行</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div className="space-y-2">
              <Label htmlFor="run-dataset">数据集</Label>
              <select
                id="run-dataset"
                data-testid="run-dataset-select"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={runDatasetId}
                onChange={(event) => setRunDatasetId(event.target.value)}
              >
                <option value="">请选择</option>
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name} (v{dataset.version})
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="run-agent">Agent id</Label>
              <Input
                id="run-agent"
                data-testid="run-agent-input"
                value={runAgentId}
                onChange={(event) => setRunAgentId(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="run-agent-version">Agent 版本 id</Label>
              <Input
                id="run-agent-version"
                data-testid="run-agent-version-input"
                value={runAgentVersionId}
                onChange={(event) => setRunAgentVersionId(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="run-idempotency">幂等键（可选）</Label>
              <Input
                id="run-idempotency"
                data-testid="run-idempotency-input"
                value={runIdempotencyKey}
                onChange={(event) => setRunIdempotencyKey(event.target.value)}
              />
            </div>
          </div>

          <RequirePermission code="evaluation:run">
            <Button
              size="sm"
              data-testid="run-start-button"
              onClick={handleStartRun}
              disabled={startRun.isPending}
            >
              启动评测
            </Button>
          </RequirePermission>

          {runDetail ? <RunResultView run={runDetail.run} results={runDetail.results} /> : null}
        </CardContent>
      </Card>

      {/* ③ 回归对比 */}
      <Card>
        <CardHeader>
          <CardTitle>回归对比</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="compare-run">当前 Run id</Label>
              <Input
                id="compare-run"
                data-testid="compare-run-input"
                value={compareRunId}
                onChange={(event) => setCompareRunId(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="compare-baseline">Baseline Run id</Label>
              <Input
                id="compare-baseline"
                data-testid="compare-baseline-input"
                value={compareBaselineId}
                onChange={(event) => setCompareBaselineId(event.target.value)}
              />
            </div>
            <div className="flex items-end">
              <RequirePermission code="evaluation:read">
                <Button
                  size="sm"
                  data-testid="compare-button"
                  onClick={handleCompare}
                  disabled={compare.isPending}
                >
                  对比
                </Button>
              </RequirePermission>
            </div>
          </div>

          <p className="text-xs text-muted-foreground" data-testid="compare-na-hint">
            缺失指标显示 N/A，不视为 0。
          </p>

          {compareReport ? <CompareReportView report={compareReport} /> : null}
        </CardContent>
      </Card>
    </div>
  );
}
