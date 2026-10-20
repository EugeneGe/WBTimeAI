import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, RefreshCw, Workflow as WorkflowIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import "@xyflow/react/dist/style.css";

import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateWorkflow,
  useCancelWorkflowRun,
  useDeleteWorkflow,
  usePublishWorkflow,
  useRunWorkflow,
  useUpdateWorkflow,
  useWorkflows,
  useWorkflowRun,
  useWorkflowVersions,
} from "@/hooks/useWorkflow";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/query";
import {
  WORKFLOW_NODE_TYPES,
  isTerminalWorkflowRunStatus,
  type PublishWorkflowRequest,
  type WorkflowNodeType,
  type WorkflowResponse,
  type WorkflowReplayNode,
  type WorkflowVersionResponse,
} from "@/types";

/** 画布节点数据（`label` ＝ 节点 key；`nodeType` ∈ 8 类；`config` 供属性面板只读预览）。 */
type DesignerNodeData = {
  label: string;
  nodeType: WorkflowNodeType;
  config: Record<string, unknown>;
};
/** 画布节点（统一自定义类型 `workflow`）。 */
type DesignerNode = Node<DesignerNodeData, "workflow">;

/** 翻译函数签名（非组件 helper 经参数接收，**不**在模块顶层取 `t`）。 */
type Translate = (key: string, params?: Record<string, string | number>) => string;

/**
 * 8 类节点的展示名（i18n key）+ 2 字母方块（左列节点面板 / 节点卡共用）。
 *
 * 🔴 模块顶层**不**取 `t`：只存 `labelKey`，组件内经 `t(meta.labelKey)` 解析；
 *    `abbr` 为技术缩写（AG / TO / …），**不翻译**。
 */
const NODE_TYPE_META = new Map<WorkflowNodeType, { labelKey: string; abbr: string }>([
  ["AGENT", { labelKey: "workflow.nodeType.AGENT", abbr: "AG" }],
  ["TOOL", { labelKey: "workflow.nodeType.TOOL", abbr: "TO" }],
  ["MCP", { labelKey: "workflow.nodeType.MCP", abbr: "MC" }],
  ["CONDITION", { labelKey: "workflow.nodeType.CONDITION", abbr: "CD" }],
  ["PARALLEL", { labelKey: "workflow.nodeType.PARALLEL", abbr: "PL" }],
  ["LOOP", { labelKey: "workflow.nodeType.LOOP", abbr: "LP" }],
  ["HUMAN_APPROVAL", { labelKey: "workflow.nodeType.HUMAN_APPROVAL", abbr: "HA" }],
  ["END", { labelKey: "workflow.nodeType.END", abbr: "EN" }],
]);

/** 节点左 3px 类型色条（墨蓝 / 序金 / 琥珀 / 灰虚线）。 */
const NODE_ACCENT_CLASS = new Map<WorkflowNodeType, string>([
  ["AGENT", "border-l-[#17325C]"],
  ["TOOL", "border-l-[#17325C]"],
  ["MCP", "border-l-[#17325C]"],
  ["CONDITION", "border-l-[#F5B941]"],
  ["PARALLEL", "border-l-[#17325C]"],
  ["LOOP", "border-l-[#17325C]"],
  ["HUMAN_APPROVAL", "border-l-[#8A6322] bg-[#FDF8EC]"],
  ["END", "border-l-[#97A2B8] border-dashed"],
]);

/**
 * 取节点元信息（后端 `type` 为字符串，未知类型 `labelKey` 为 `null` → 回落原字面值）。
 */
function nodeMeta(nodeType: string): { labelKey: string | null; abbr: string } {
  const known = NODE_TYPE_META.get(nodeType as WorkflowNodeType);
  if (known) {
    return known;
  }
  return { labelKey: null, abbr: nodeType.slice(0, 2).toUpperCase() };
}

/** 节点展示名（已知类型走 i18n；未知类型原样展示后端字面值）。 */
function nodeTypeLabel(nodeType: string, t: Translate): string {
  const { labelKey } = nodeMeta(nodeType);
  return labelKey === null ? nodeType : t(labelKey);
}

/** 取节点左色条类（未知类型回落墨蓝）。 */
function nodeAccentClass(nodeType: string): string {
  return NODE_ACCENT_CLASS.get(nodeType as WorkflowNodeType) ?? "border-l-[#17325C]";
}

/** 两位补零。 */
function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

/** 时间戳 → `MM-DD HH:mm`（缺失 / 非法值回落 `--`）。 */
function formatStamp(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(
    date.getMinutes(),
  )}`;
}

/** 运行耗时（`started_at` → `completed_at`；缺失 / 非法 / 倒挂回落 `--`）。 */
function formatDuration(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined,
): string {
  if (!startedAt || !completedAt) {
    return "--";
  }
  const start = new Date(startedAt).getTime();
  const end = new Date(completedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    return "--";
  }
  const elapsed = end - start;
  return elapsed >= 1_000 ? `${(elapsed / 1_000).toFixed(1)}s` : `${elapsed}ms`;
}

/**
 * 运行 / 节点状态视觉基调（复用 Tasks 页语义四色：成功=绿 / 进行中=金 / 失败=红 / 其余=灰）。
 *
 * - `WAITING_APPROVAL` 走**琥珀**（`#8A6322` / `#F7EBCF`，与画布 `HUMAN_APPROVAL` 节点色条同源，
 *   与 `RUNNING` 的序金**可区分**；语义：停在人工审批节点，**非终态**）；
 * - 节点级 `SKIPPED` 与 Run 级 `CANCELLED` / `PENDING` 同走中性灰（无情绪色）。
 */
const RUN_STATUS_TONES: Record<string, { dot: string; pill: string }> = {
  SUCCEEDED: { dot: "bg-[#4A7C63]", pill: "bg-[#EDF4F0] text-[#3C6650]" },
  RUNNING: { dot: "bg-[#F5B941]", pill: "bg-[#FDF8EC] text-[#8A6322]" },
  WAITING_APPROVAL: { dot: "bg-[#8A6322]", pill: "bg-[#F7EBCF] text-[#8A6322]" },
  FAILED: { dot: "bg-[#A84452]", pill: "bg-[#FBEEF0] text-[#8F3A47]" },
};

/** 中性基调（`PENDING` / `CANCELLED` / `SKIPPED` / 未知态）。 */
const RUN_NEUTRAL_TONE = { dot: "bg-[#97A2B8]", pill: "bg-[#F1F4F9] text-[#5A6478]" };

/** 运行 / 节点状态胶囊（圆点 + 文案 + 浅底；未知状态回中性灰）。 */
function RunStatusBadge({ status, testId }: { status: string; testId?: string }) {
  const tone = RUN_STATUS_TONES[status] ?? RUN_NEUTRAL_TONE;
  return (
    <span
      data-testid={testId}
      title={status}
      className={cn(
        "inline-flex flex-none items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium leading-4",
        tone.pill,
      )}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 flex-none rounded-full", tone.dot)} />
      {status}
    </span>
  );
}

/** 运行短 id（`#` + 末 4 位；完整 id 走 `title`）。 */
function shortRunId(runId: string): string {
  return `#${runId.slice(-4)}`;
}

/**
 * 单个节点运行态行（`node_key` / 状态 / 尝试次数 / 耗时）。
 *
 * 节点带 `approval_id`（`HUMAN_APPROVAL` 节点挂起审批）→ 额外标注「待审批」。
 * 🔴 **仅标注**：跳转 / 联动审批页由另一路（approvals 域）负责，本页不做。
 */
function RunNodeRow({ node }: { node: WorkflowReplayNode }) {
  const { t } = useTranslation();
  return (
    <li
      data-testid={`workflow-run-node-${node.node_key}`}
      className="flex items-center gap-2 rounded-md border border-border/60 bg-card px-2 py-1"
    >
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground">
        {node.node_key}
      </span>
      {node.approval_id ? (
        <span
          className="shrink-0 rounded-full border border-[#EFE0BC] bg-[#F7EBCF] px-1.5 py-0.5 text-[10px] leading-4 text-[#8A6322]"
          title={`approval_id: ${node.approval_id}`}
          data-testid={`workflow-run-node-approval-${node.node_key}`}
        >
          {t("workflow.run.nodeWaitingApproval")}
        </span>
      ) : null}
      <RunStatusBadge status={node.status} />
      <span className="shrink-0 text-[10px] text-muted-foreground">
        {t("workflow.run.nodeAttempt", { attempt: node.attempt })}
      </span>
      <span
        className="w-10 shrink-0 text-right font-mono text-[10px] text-muted-foreground"
        data-testid={`workflow-run-node-duration-${node.node_key}`}
      >
        {formatDuration(node.started_at, node.completed_at)}
      </span>
    </li>
  );
}

/**
 * 运行面板（就地展开的灰底内嵌卡，**非**抽屉 / 弹层；范式对齐 `pages/Tasks.tsx::TaskDetail`）。
 *
 * - 头：状态徽标 + 短 run id + 取消 + 收起；
 * - 体：错误条（有 `error` 时红色）/ 起止时间 / 节点运行态列表；
 * - `useWorkflowRun` 自带非终态 2s 轮询，终态自动停止（`INLINE` 下通常首次即终态）。
 */
function WorkflowRunPanel({
  workflowId,
  runId,
  onCollapse,
}: {
  workflowId: string;
  runId: string;
  onCollapse: () => void;
}) {
  const { t } = useTranslation();
  const runQuery = useWorkflowRun(workflowId, runId, true);
  const cancelRun = useCancelWorkflowRun();
  const [feedback, setFeedback] = useState<string | null>(null);

  const run = runQuery.data;
  const isTerminal = isTerminalWorkflowRunStatus(run?.status);

  if (runQuery.isError) {
    return (
      <div
        className="mt-3 shrink-0 rounded-lg border border-[#F0D5DA] bg-[#FBEEF0] p-3"
        data-testid="workflow-run-panel-error"
      >
        <p className="text-[11px] text-[#8F3A47]">
          {t("workflow.run.loadFailed", { message: toApiError(runQuery.error).message })}
        </p>
        <div className="mt-2 flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-[11px]"
            data-testid="workflow-run-retry"
            onClick={() => void runQuery.refetch()}
          >
            {t("common.retry")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-[11px] text-muted-foreground"
            onClick={onCollapse}
          >
            {t("workflow.run.collapse")}
          </Button>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div
        className="mt-3 shrink-0 space-y-2 rounded-lg border bg-[#FBFCFE] p-3"
        data-testid="workflow-run-loading"
      >
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }

  const nodeList = run.nodes ?? [];

  return (
    <div
      className="mt-3 max-h-56 shrink-0 overflow-y-auto rounded-lg border bg-[#FBFCFE] p-3"
      data-testid="workflow-run-panel"
    >
      <div className="flex items-center gap-2">
        <span className="flex-none text-xs font-medium text-foreground">
          {t("workflow.run.title")}
        </span>
        <RunStatusBadge status={run.status} testId="workflow-run-status" />
        <span
          className="min-w-0 truncate font-mono text-[10px] text-muted-foreground"
          title={run.run_id}
          data-testid="workflow-run-id"
        >
          {shortRunId(run.run_id)}
        </span>
        <div className="ml-auto flex flex-none items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2 text-[11px]"
            data-testid="workflow-run-cancel"
            title={isTerminal ? t("workflow.run.terminalTitle") : t("workflow.run.cancelTitle")}
            disabled={isTerminal || cancelRun.isPending}
            onClick={() =>
              cancelRun.mutate(
                { workflowId, runId },
                {
                  onSuccess: (detail) =>
                    setFeedback(t("workflow.run.cancelRequested", { status: detail.status })),
                  onError: (error) => setFeedback(toApiError(error).message),
                },
              )
            }
          >
            {t("workflow.run.cancel")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px] text-muted-foreground"
            data-testid="workflow-run-collapse"
            onClick={onCollapse}
          >
            {t("workflow.run.collapse")}
          </Button>
        </div>
      </div>

      {feedback ? (
        <p className="mt-2 text-[11px] text-muted-foreground" data-testid="workflow-run-feedback">
          {feedback}
        </p>
      ) : null}

      {run.error ? (
        <p
          className="mt-2 rounded-md border border-[#F0D5DA] bg-[#FBEEF0] px-2 py-1 text-[11px] text-[#8F3A47]"
          data-testid="workflow-run-error"
        >
          {run.error}
        </p>
      ) : null}

      <dl className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <div className="flex items-center gap-1">
          <dt className="text-[10px] text-muted-foreground">{t("workflow.run.trigger")}</dt>
          <dd className="font-mono text-[10px] text-foreground" data-testid="workflow-run-trigger">
            {run.trigger || "--"}
          </dd>
        </div>
        <div className="flex items-center gap-1">
          <dt className="text-[10px] text-muted-foreground">{t("workflow.run.startedAt")}</dt>
          <dd className="text-[10px] text-foreground" data-testid="workflow-run-started-at">
            {formatStamp(run.started_at)}
          </dd>
        </div>
        <div className="flex items-center gap-1">
          <dt className="text-[10px] text-muted-foreground">{t("workflow.run.completedAt")}</dt>
          <dd className="text-[10px] text-foreground" data-testid="workflow-run-completed-at">
            {formatStamp(run.completed_at)}
          </dd>
        </div>
        <div className="flex items-center gap-1">
          <dt className="text-[10px] text-muted-foreground">{t("workflow.run.duration")}</dt>
          <dd className="font-mono text-[10px] text-foreground" data-testid="workflow-run-duration">
            {formatDuration(run.started_at, run.completed_at)}
          </dd>
        </div>
        <div className="flex items-center gap-1">
          <dt className="text-[10px] text-muted-foreground">{t("workflow.field.nodes")}</dt>
          <dd className="text-[10px] text-foreground" data-testid="workflow-run-node-count">
            {nodeList.length}
          </dd>
        </div>
      </dl>

      <div className="mt-2" data-testid="workflow-run-nodes">
        <h3 className="mb-1 text-[10px] font-medium text-muted-foreground">
          {t("workflow.run.nodesTitle")}
        </h3>
        {nodeList.length === 0 ? (
          <p className="text-[10px] text-muted-foreground" data-testid="workflow-run-nodes-empty">
            {t("workflow.run.nodesEmpty")}
          </p>
        ) : (
          <ul className="space-y-1">
            {nodeList.map((node) => (
              <RunNodeRow key={node.id} node={node} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** 自定义节点渲染（168px 卡：key · 类型中文名 + 类型英文 + 上下连接点）。 */
function WorkflowNodeCard({ data, selected }: NodeProps<DesignerNode>) {
  const { t } = useTranslation();
  return (
    <div
      data-testid={`rf-node-${data.label}`}
      className={cn(
        "flex w-[168px] flex-col gap-[3px] rounded-lg border border-border border-l-[3px] bg-card px-2.5 py-2 shadow-sm",
        nodeAccentClass(data.nodeType),
        selected && "border-[#F5B941] ring-2 ring-[#F5B941]/25",
      )}
    >
      <Handle type="target" position={Position.Top} />
      <span className="truncate text-[11px] font-medium text-primary">
        {data.label} · {nodeTypeLabel(data.nodeType, t)}
      </span>
      <span className="font-mono text-[9px] text-muted-foreground">{data.nodeType}</span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const NODE_TYPES = { workflow: WorkflowNodeCard };

/** 属性面板的只读键值行。 */
function PropertyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="shrink-0 text-[10px] text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate font-mono text-[10px] text-foreground">{value}</span>
    </div>
  );
}

/**
 * Workflow Designer（W6 / T2-35；设计 §2.5 / 裁定 §3.4；B-21 三栏全高工作台）。
 *
 * - **三栏全高**：左列（工作流列表 + 新建 + 节点面板）/ 中列（画布吃满剩余高度）/
 *   右列（只读属性 + 不可变版本）；页面本身不纵向滚动，滚动只发生在左列列表与右列版本区；
 * - **React Flow v12** 画布：8 类节点（`AGENT/TOOL/MCP/CONDITION/PARALLEL/LOOP/
 *   HUMAN_APPROVAL/END`）↔ `workflow_node`；连线 ↔ `workflow_edge`；
 * - **保存 = 新 `workflow_version`**（不可变；调用 `/workflows/{id}/publish`）；
 * - **重命名**（`PUT /workflows/{id}` 只传 `{name}`）/**删除**（`DELETE` → 204）；
 * - **版本载入**：把历史版本 definition 回灌画布预览，保存仍生成新版本；
 * - **运行**：`POST /workflows/{id}/run`（显式 `Accept: application/json` → JSON 降级，
 *   `INLINE` **同步执行到终态**）→ 画布下方就地展开运行面板（状态 / 节点运行态 / 取消）；
 * - 条件编辑（`CONDITION` 节点 `config`）受**白名单约束**，**不执行任意代码**。
 */
export function WorkflowDesigner() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: workflows, isLoading } = useWorkflows();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [nodes, setNodes] = useState<DesignerNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  /** 画布当前承载的版本号（与「最新版本」分离：载入历史版本后不再谎报最新版）。 */
  const [canvasVersion, setCanvasVersion] = useState<string | null>(null);
  /** 当前运行面板展示的 run id（`null` = 面板关闭）。 */
  const [runId, setRunId] = useState<string | null>(null);

  // 重命名 / 删除弹窗状态。
  const [renameTarget, setRenameTarget] = useState<WorkflowResponse | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<WorkflowResponse | null>(null);

  const { data: versions } = useWorkflowVersions(selectedId);
  const createWorkflow = useCreateWorkflow();
  const updateWorkflow = useUpdateWorkflow();
  const deleteWorkflow = useDeleteWorkflow();
  const publish = usePublishWorkflow();
  const runWorkflow = useRunWorkflow();

  // 仅在「切换 Workflow」时把最新版本回灌画布（避免覆盖用户编辑 / 版本载入结果）。
  const loadedFor = useRef<string | null>(null);

  const workflowList = workflows ?? [];
  const versionList = versions ?? [];
  const selectedWorkflow = workflowList.find((item) => item.id === selectedId) ?? null;
  const latestVersion = versionList.length > 0 ? versionList[versionList.length - 1] : null;
  const selectedNode = nodes.find((node) => node.id === selectedNodeKey) ?? null;

  /** 画布头展示的版本号：优先「画布当前版本」，无则回落到最新版本。 */
  const latestVersionLabel = latestVersion?.version ?? null;
  const canvasVersionLabel = canvasVersion ?? latestVersionLabel;
  /** 画布承载的是**历史版本**（非最新）→ 标签加「（历史）」琥珀提示。 */
  const isHistoricalCanvas = canvasVersion !== null && canvasVersionLabel !== latestVersionLabel;

  /** 把某个版本的 definition 回灌画布（切换工作流 / 版本「载入」共用）。 */
  const applyVersion = useCallback((version: WorkflowVersionResponse): void => {
    const definition = version.definition;
    setNodes(
      definition.nodes.map((node, index) => ({
        id: node.key,
        type: "workflow" as const,
        position: {
          x: Number(node.position?.x ?? 80 + (index % 4) * 180),
          y: Number(node.position?.y ?? 60 + Math.floor(index / 4) * 120),
        },
        data: {
          label: node.key,
          nodeType: node.type as WorkflowNodeType,
          config: node.config ?? {},
        },
      })),
    );
    setEdges(
      definition.edges.map((edge) => ({
        id: `${edge.from}->${edge.to}`,
        source: edge.from,
        target: edge.to,
      })),
    );
    setSelectedNodeKey(null);
    // 画布承载版本随回灌同步（切换工作流 / 版本载入 / 发布共用同一真相）。
    setCanvasVersion(version.version);
  }, []);

  useEffect(() => {
    if (!selectedId || loadedFor.current === selectedId || !versions) {
      return;
    }
    loadedFor.current = selectedId;
    const latest = versions.length > 0 ? versions[versions.length - 1] : null;
    if (!latest) {
      setNodes([]);
      setEdges([]);
      setSelectedNodeKey(null);
      setCanvasVersion(null);
      return;
    }
    applyVersion(latest);
  }, [selectedId, versions, applyVersion]);

  const selectWorkflow = (workflowId: string): void => {
    if (workflowId === selectedId) {
      return;
    }
    loadedFor.current = null;
    setSelectedId(workflowId);
    setSelectedNodeKey(null);
    setCanvasVersion(null);
    // 切换工作流 → 上一次的运行面板不再属于当前画布。
    setRunId(null);
  };

  const handleAddNode = (nodeType: WorkflowNodeType): void => {
    setNodes((prev) => {
      const index = prev.length + 1;
      const id = `n${index}`;
      return [
        ...prev,
        {
          id,
          type: "workflow" as const,
          position: {
            x: 80 + (index % 4) * 180,
            y: 60 + Math.floor(index / 4) * 120,
          },
          data: { label: id, nodeType, config: {} },
        },
      ];
    });
  };

  const onNodesChange = useCallback(
    (changes: NodeChange<DesignerNode>[]) =>
      setNodes((current) => applyNodeChanges(changes, current)),
    [],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((current) => applyEdgeChanges(changes, current)),
    [],
  );

  const onConnect = useCallback((connection: Connection) => {
    setEdges((current) =>
      addEdge({ ...connection, id: `${connection.source}->${connection.target}` }, current),
    );
  }, []);

  const handleNodeClick = useCallback((_event: ReactMouseEvent, node: DesignerNode): void => {
    setSelectedNodeKey(node.id);
  }, []);

  /** 画布节点：把「当前选中」投影到 React Flow 的 `selected`（节点卡态）。 */
  const canvasNodes = useMemo(
    () => nodes.map((node) => ({ ...node, selected: node.id === selectedNodeKey })),
    [nodes, selectedNodeKey],
  );

  const handleRefresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.workflows });
    if (selectedId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflowVersions(selectedId) });
    }
    setFeedback(t("workflow.feedback.refreshed"));
  };

  const handleCreate = (): void => {
    if (!newName.trim()) {
      setFeedback(t("workflow.feedback.nameRequired"));
      return;
    }
    createWorkflow.mutate(
      { name: newName.trim() },
      {
        onSuccess: (workflow: WorkflowResponse) => {
          setNewName("");
          loadedFor.current = null;
          setSelectedId(workflow.id);
          setSelectedNodeKey(null);
          setRunId(null);
          setFeedback(t("workflow.feedback.created"));
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const saveBlockedReason = !selectedId
    ? t("workflow.feedback.selectRequired")
    : nodes.length === 0
      ? t("workflow.feedback.canvasEmpty")
      : publish.isPending
        ? t("workflow.feedback.saving")
        : null;

  const handleSave = (): void => {
    if (!selectedId) {
      setFeedback(t("workflow.feedback.selectRequired"));
      return;
    }
    if (nodes.length === 0) {
      setFeedback(t("workflow.feedback.canvasEmpty"));
      return;
    }
    const payload: PublishWorkflowRequest = {
      nodes: nodes.map((node) => ({
        key: node.id,
        type: node.data.nodeType,
        // 条件编辑受白名单约束（不执行任意代码）；本轮仅提交空 config。
        config: {},
        position: { x: node.position.x, y: node.position.y },
      })),
      edges: edges.map((edge) => ({
        from: edge.source,
        to: edge.target,
        condition: null,
      })),
      entry: nodes[0]?.id ?? null,
    };
    publish.mutate(
      { workflowId: selectedId, payload },
      {
        onSuccess: (version) => {
          // 保存后画布内容即该新版本（不可变快照）→ 版本标签同步为新版本。
          setCanvasVersion(version.version);
          setFeedback(t("workflow.feedback.saved", { version: version.version }));
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handleLoadVersion = (version: WorkflowVersionResponse): void => {
    applyVersion(version);
    // `loadedFor.current` 保持为当前 id：载入只是预览，防止 effect 又覆盖回最新版本。
    loadedFor.current = selectedId;
    setFeedback(t("workflow.feedback.loaded", { version: version.version }));
  };

  const runBlockedReason = !selectedId
    ? t("workflow.feedback.selectRequired")
    : runWorkflow.isPending
      ? t("workflow.feedback.running")
      : null;

  /**
   * 运行当前 Workflow（`INLINE` **同步执行到终态**）。
   *
   * 请求返回即拿到 `run_id`（裸 JSON 摘要）→ 面板拉重放快照渲染节点运行态。
   * 同步语义下运行期间**无实时进度**（无法逐节点刷新），按钮以 loading 遮断重复点击。
   */
  const handleRun = (): void => {
    if (!selectedId) {
      setFeedback(t("workflow.feedback.selectRequired"));
      return;
    }
    // 关掉上一次的运行面板，避免旧 run 与新请求交错。
    setRunId(null);
    setFeedback(t("workflow.feedback.running"));
    runWorkflow.mutate(
      {
        workflowId: selectedId,
        payload: { execution_mode: "INLINE", trigger: "user", input: {} },
      },
      {
        onSuccess: (digest) => {
          setRunId(digest.run_id);
          setFeedback(
            digest.error
              ? t("workflow.feedback.runFinishedWithError", {
                  status: digest.status,
                  error: digest.error,
                })
              : t("workflow.feedback.runFinished", { status: digest.status }),
          );
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const openRename = (workflow: WorkflowResponse): void => {
    setRenameTarget(workflow);
    setRenameValue(workflow.name);
    setRenameError(null);
  };

  const closeRename = (): void => {
    setRenameTarget(null);
    setRenameValue("");
    setRenameError(null);
  };

  const handleRenameSubmit = (): void => {
    const target = renameTarget;
    if (!target) {
      return;
    }
    const nextName = renameValue.trim();
    if (!nextName) {
      setRenameError(t("workflow.feedback.nameRequired"));
      return;
    }
    updateWorkflow.mutate(
      { workflowId: target.id, payload: { name: nextName } },
      {
        onSuccess: () => {
          closeRename();
          setFeedback(t("workflow.feedback.renamed"));
        },
        onError: (error) => setRenameError(toApiError(error).message),
      },
    );
  };

  const handleDeleteConfirm = (): void => {
    const target = deleteTarget;
    if (!target) {
      return;
    }
    deleteWorkflow.mutate(target.id, {
      onSuccess: () => {
        setDeleteTarget(null);
        if (selectedId === target.id) {
          loadedFor.current = null;
          setSelectedId(null);
          setSelectedNodeKey(null);
          setNodes([]);
          setEdges([]);
          setCanvasVersion(null);
          setRunId(null);
        }
        setFeedback(t("workflow.feedback.deleted"));
      },
      onError: (error) => setFeedback(toApiError(error).message),
    });
  };

  return (
    <PageContainer width="full" className="py-4">
      <div className="flex flex-col gap-3 lg:h-[calc(100dvh-8.5rem)] lg:overflow-hidden">
        {/* 页头（固定高度，不随三栏滚动） */}
        <header className="flex shrink-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">{t("workflow.title")}</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("workflow.subtitle", { count: workflowList.length })}
            </p>
          </div>
          <div className="flex min-w-0 shrink items-center gap-2">
            {feedback ? (
              <span
                data-testid="workflow-feedback"
                className="truncate text-right text-[11px] text-muted-foreground"
              >
                {feedback}
              </span>
            ) : null}
            <button
              type="button"
              data-testid="workflow-refresh"
              aria-label={t("workflow.refresh")}
              title={t("workflow.refresh")}
              onClick={handleRefresh}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        </header>

        {/* 三栏（`<lg` 纵向堆叠，画布固定 520px；`lg+` 三栏全高、页面不滚动） */}
        <div className="grid grid-cols-1 gap-3 lg:min-h-0 lg:flex-1 lg:grid-cols-[200px_1fr_240px] xl:grid-cols-[224px_1fr_268px]">
          {/* 左列：工作流列表 + 新建 + 节点面板（单卡三段） */}
          <Card className="flex min-h-0 flex-col overflow-hidden">
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
              <span className="text-xs font-medium text-foreground">Workflows</span>
              <span className="text-[10px] text-muted-foreground">{workflowList.length}</span>
            </div>

            {isLoading ? (
              <div className="shrink-0 space-y-1.5 p-2" data-testid="workflow-list">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
              </div>
            ) : workflowList.length === 0 ? (
              <div
                className="flex shrink-0 flex-col items-center justify-center gap-1 px-3 py-6 text-center"
                data-testid="workflow-list"
              >
                <WorkflowIcon
                  className="h-[34px] w-[34px] text-muted-foreground/40"
                  strokeWidth={1.4}
                />
                <span className="text-[13px] text-foreground">
                  {t("workflow.list.empty.title")}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {t("workflow.list.empty.description")}
                </span>
              </div>
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto p-2" data-testid="workflow-list">
                <ul className="space-y-1">
                  {workflowList.map((workflow) => {
                    const isActive = workflow.id === selectedId;
                    return (
                      <li key={workflow.id} className="group relative">
                        <button
                          type="button"
                          data-testid={`workflow-item-${workflow.name}`}
                          onClick={() => selectWorkflow(workflow.id)}
                          className={cn(
                            "w-full rounded-lg border px-2 py-1.5 pr-7 text-left transition-colors",
                            isActive
                              ? "border-accent bg-[#FDF8EC]"
                              : "border-transparent hover:bg-secondary/60",
                          )}
                        >
                          <span className="block truncate text-[12px] font-medium text-foreground">
                            {workflow.name}
                          </span>
                          <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">
                            {workflow.status} · {formatStamp(workflow.created_at)}
                          </span>
                        </button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              data-testid={`workflow-more-${workflow.name}`}
                              aria-label={t("workflow.item.moreActions", { name: workflow.name })}
                              className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
                            >
                              <MoreHorizontal className="h-3.5 w-3.5" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-28">
                            <DropdownMenuItem
                              data-testid={`workflow-rename-${workflow.name}`}
                              onSelect={() => openRename(workflow)}
                            >
                              {t("workflow.item.rename")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              data-testid={`workflow-delete-${workflow.name}`}
                              className="text-destructive focus:text-destructive"
                              onSelect={() => setDeleteTarget(workflow)}
                            >
                              {t("workflow.item.delete")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {/* 新建段 */}
            <div className="shrink-0 border-t border-border px-2 py-2">
              <span className="mb-1 block text-[11px] text-muted-foreground">
                {t("workflow.create.sectionLabel")}
              </span>
              <div className="flex items-center gap-1.5">
                <Input
                  data-testid="workflow-name-input"
                  value={newName}
                  placeholder={t("workflow.field.name")}
                  aria-label={t("workflow.create.nameAriaLabel")}
                  onChange={(event) => setNewName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      handleCreate();
                    }
                  }}
                  className="h-7 flex-1 px-2 text-xs"
                />
                <Button
                  size="sm"
                  data-testid="workflow-create-submit"
                  onClick={handleCreate}
                  disabled={createWorkflow.isPending}
                  className="h-7 shrink-0 px-2 text-[11px]"
                >
                  {t("workflow.create.submit")}
                </Button>
              </div>
            </div>

            {/* 节点面板段 */}
            <div className="flex shrink-0 flex-col border-t border-border pt-2">
              <div className="flex items-center justify-between px-3 pb-1">
                <span className="text-xs font-medium text-foreground">
                  {t("workflow.field.nodes")}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {t("workflow.palette.hint")}
                </span>
              </div>
              <div className="max-h-[248px] overflow-y-auto px-2 pb-2" data-testid="node-palette">
                {WORKFLOW_NODE_TYPES.map((nodeType) => {
                  const meta = nodeMeta(nodeType);
                  const isApproval = nodeType === "HUMAN_APPROVAL";
                  return (
                    <button
                      key={nodeType}
                      type="button"
                      data-testid={`add-node-${nodeType}`}
                      onClick={() => handleAddNode(nodeType)}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md border px-1.5 py-1 text-left transition-colors",
                        isApproval
                          ? "border-[#EFE0BC] bg-[#FDF8EC] text-[#8A6322] hover:bg-[#F7EBCF]"
                          : "border-transparent hover:bg-secondary/60",
                      )}
                    >
                      <span
                        className={cn(
                          "flex h-4 w-4 shrink-0 items-center justify-center rounded font-mono text-[8px]",
                          isApproval
                            ? "bg-[#F7EBCF] text-[#8A6322]"
                            : "bg-secondary text-foreground",
                        )}
                      >
                        {meta.abbr}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[12px]">
                        {nodeTypeLabel(nodeType, t)}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 font-mono text-[9px]",
                          isApproval ? "text-[#8A6322]/70" : "text-muted-foreground",
                        )}
                      >
                        {nodeType}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </Card>

          {/* 中列：画布卡（卡头 + 吃满剩余高度） */}
          <Card className="flex min-h-0 flex-col overflow-hidden">
            <div className="flex h-[38px] shrink-0 items-center gap-2 border-b border-border px-3">
              <span className="min-w-0 truncate text-[12px] font-medium text-foreground">
                {selectedWorkflow?.name ?? t("workflow.canvas.noSelection")}
              </span>
              {selectedWorkflow ? (
                <Badge
                  variant="outline"
                  className="shrink-0 px-1.5 py-0 text-[9px] font-normal leading-4"
                >
                  {selectedWorkflow.status}
                </Badge>
              ) : null}
              <span
                data-testid="workflow-canvas-version"
                className="shrink-0 font-mono text-[10px] text-muted-foreground"
              >
                {canvasVersionLabel ? (
                  <>
                    <span>{canvasVersionLabel}</span>
                    {isHistoricalCanvas ? (
                      <span className="text-[#8A6322]">{t("workflow.canvas.historical")}</span>
                    ) : null}
                    {" · "}
                  </>
                ) : null}
                {t("workflow.canvas.counts", { nodeCount: nodes.length, edgeCount: edges.length })}
              </span>
              <span className="min-w-2 flex-1" />
              <Button
                variant="outline"
                size="sm"
                data-testid="workflow-run"
                disabled={runBlockedReason !== null}
                title={runBlockedReason ?? t("workflow.canvas.runTitle")}
                onClick={handleRun}
                className="h-6 shrink-0 px-2 text-[11px]"
              >
                {runWorkflow.isPending ? t("workflow.canvas.running") : t("workflow.canvas.run")}
              </Button>
              <Button
                size="sm"
                data-testid="workflow-save-submit"
                disabled={saveBlockedReason !== null}
                title={saveBlockedReason ?? t("workflow.canvas.save")}
                onClick={handleSave}
                className="h-6 shrink-0 px-2 text-[11px]"
              >
                {t("workflow.canvas.save")}
              </Button>
            </div>

            <div
              data-testid="workflow-canvas"
              className="relative h-[520px] w-full lg:h-auto lg:min-h-0 lg:flex-1"
            >
              <ReactFlow
                nodes={canvasNodes}
                edges={edges}
                nodeTypes={NODE_TYPES}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={handleNodeClick}
                proOptions={{ hideAttribution: true }}
                fitView
              >
                <Background gap={16} size={1} color="#D9E0EC" />
                <Controls />
              </ReactFlow>
              {nodes.length === 0 ? (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                  <div className="text-center">
                    <p className="text-xs text-foreground">{t("workflow.canvas.empty.title")}</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      {t("workflow.canvas.empty.description")}
                    </p>
                  </div>
                </div>
              ) : null}
            </div>

            {/* 运行面板（就地展开；非终态 2s 轮询，终态停止） */}
            {selectedId && runId ? (
              <div className="shrink-0 px-2 pb-2" data-testid="workflow-run-panel-wrap">
                <WorkflowRunPanel
                  workflowId={selectedId}
                  runId={runId}
                  onCollapse={() => setRunId(null)}
                />
              </div>
            ) : null}
          </Card>

          {/* 右列：只读属性 + 不可变版本 */}
          <div className="flex min-h-0 flex-col gap-3">
            <Card
              className="flex shrink-0 flex-col overflow-hidden"
              data-testid="workflow-property-panel"
            >
              <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
                <span className="text-xs font-medium text-foreground">
                  {t("workflow.property.title")}
                </span>
                <span className="text-[10px] text-muted-foreground">{selectedNode?.id ?? "—"}</span>
              </div>
              {selectedNode ? (
                <div className="space-y-1.5 p-3">
                  <PropertyRow label="key" value={selectedNode.id} />
                  <PropertyRow
                    label={t("workflow.property.type")}
                    value={selectedNode.data.nodeType}
                  />
                  <PropertyRow
                    label={t("workflow.property.position")}
                    value={`${Math.round(selectedNode.position.x)}, ${Math.round(
                      selectedNode.position.y,
                    )}`}
                  />
                  <pre className="max-h-28 overflow-auto rounded-md bg-secondary/60 p-2 font-mono text-[9px] leading-relaxed text-foreground">
                    {JSON.stringify(selectedNode.data.config ?? {}, null, 2)}
                  </pre>
                  <p className="text-[10px] leading-relaxed text-muted-foreground">
                    {t("workflow.property.note")}
                  </p>
                  <div className="flex gap-1.5 pt-0.5">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled
                      title={t("workflow.property.saveConfigHint")}
                      className="h-6 px-2 text-[11px]"
                    >
                      {t("workflow.property.saveConfig")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled
                      title={t("workflow.property.deleteNodeHint")}
                      className="h-6 px-2 text-[11px] text-destructive"
                    >
                      {t("workflow.property.deleteNode")}
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="py-6 text-center text-[11px] text-muted-foreground">
                  {t("workflow.property.empty")}
                </p>
              )}
            </Card>

            <Card className="flex min-h-0 flex-col overflow-hidden lg:flex-1">
              <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
                <span className="text-xs font-medium text-foreground">
                  {t("workflow.version.title")}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {t("workflow.version.immutable")}
                </span>
              </div>
              <ul
                className="min-h-0 flex-1 overflow-y-auto p-2"
                data-testid="workflow-version-list"
              >
                {versionList.length === 0 ? (
                  <li className="py-3 text-center text-[11px] text-muted-foreground">
                    {t("workflow.version.empty")}
                  </li>
                ) : (
                  versionList.map((version) => (
                    <li
                      key={version.id}
                      className="flex items-center gap-1.5 rounded-md px-1 py-1 hover:bg-secondary/60"
                    >
                      <span className="shrink-0 font-mono text-[11px] font-medium text-foreground">
                        {version.version}
                      </span>
                      <Badge
                        variant="outline"
                        className="shrink-0 px-1 py-0 text-[9px] font-normal leading-4"
                      >
                        {version.status}
                      </Badge>
                      <span className="min-w-0 flex-1 truncate text-right text-[10px] text-muted-foreground">
                        {formatStamp(version.created_at)}
                      </span>
                      <button
                        type="button"
                        data-testid={`workflow-version-load-${version.version}`}
                        onClick={() => handleLoadVersion(version)}
                        className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] text-primary transition-colors hover:bg-accent/20"
                      >
                        {t("workflow.version.load")}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </Card>
          </div>
        </div>
      </div>

      {/* 重命名弹窗 */}
      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            closeRename();
          }
        }}
      >
        <DialogContent data-testid="workflow-rename-dialog" className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("workflow.rename.title")}</DialogTitle>
            <DialogDescription>{t("workflow.rename.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <label htmlFor="workflow-rename-name" className="text-[11px] text-muted-foreground">
              {t("workflow.field.name")}
            </label>
            <Input
              id="workflow-rename-name"
              data-testid="workflow-rename-input"
              value={renameValue}
              onChange={(event) => {
                setRenameValue(event.target.value);
                setRenameError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  handleRenameSubmit();
                }
              }}
              className="h-8 text-xs"
            />
            {renameError ? (
              <p data-testid="workflow-rename-error" className="text-[11px] text-destructive">
                {renameError}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={closeRename}>
              {t("common.cancel")}
            </Button>
            <Button
              size="sm"
              data-testid="workflow-rename-submit"
              onClick={handleRenameSubmit}
              disabled={updateWorkflow.isPending}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认弹窗 */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
          }
        }}
      >
        <DialogContent data-testid="workflow-delete-dialog" className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("workflow.delete.title")}</DialogTitle>
            <DialogDescription>
              {t("workflow.delete.description", { name: deleteTarget?.name ?? "" })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setDeleteTarget(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              data-testid="workflow-delete-confirm"
              onClick={handleDeleteConfirm}
              disabled={deleteWorkflow.isPending}
            >
              {t("workflow.item.delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
