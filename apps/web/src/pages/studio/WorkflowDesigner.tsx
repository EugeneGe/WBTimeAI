import { useCallback, useEffect, useRef, useState } from "react";
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
import "@xyflow/react/dist/style.css";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCreateWorkflow,
  usePublishWorkflow,
  useWorkflows,
  useWorkflowVersions,
} from "@/hooks/useWorkflow";
import { toApiError } from "@/lib/api";
import {
  WORKFLOW_NODE_TYPES,
  type PublishWorkflowRequest,
  type WorkflowNodeType,
  type WorkflowResponse,
} from "@/types";

/** 画布节点数据（`label` ＝ 节点 key；`nodeType` ∈ 8 类）。 */
type DesignerNodeData = { label: string; nodeType: WorkflowNodeType };
/** 画布节点（统一自定义类型 `workflow`）。 */
type DesignerNode = Node<DesignerNodeData, "workflow">;

/** 自定义节点渲染（标题 + 类型徽标 + 上下连接点）。 */
function WorkflowNodeCard({ data }: NodeProps<DesignerNode>) {
  return (
    <div
      className="rounded-md border bg-card px-3 py-2 text-xs shadow-sm"
      data-testid={`rf-node-${data.label}`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="font-medium">{data.label}</div>
      <div className="text-muted-foreground">{data.nodeType}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const NODE_TYPES = { workflow: WorkflowNodeCard };

/**
 * Workflow Designer（W6 / T2-35；设计 §2.5 / 裁定 §3.4）。
 *
 * - **React Flow v12** 画布：8 类节点（`AGENT/TOOL/MCP/CONDITION/PARALLEL/LOOP/
 *   HUMAN_APPROVAL/END`）↔ `workflow_node`；连线 ↔ `workflow_edge`；
 * - **保存 = 新 `workflow_version`**（不可变；调用 `/workflows/{id}/publish`）；
 * - 条件编辑（`CONDITION` 节点 `config`）受**白名单约束**，**不执行任意代码**。
 */
export function WorkflowDesigner() {
  const { data: workflows, isLoading } = useWorkflows();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nodes, setNodes] = useState<DesignerNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const { data: versions } = useWorkflowVersions(selectedId);
  const createWorkflow = useCreateWorkflow();
  const publish = usePublishWorkflow();

  // 仅在「切换 Workflow」时把最新版本回灌画布（避免覆盖用户编辑）。
  const loadedFor = useRef<string | null>(null);

  useEffect(() => {
    if (!selectedId || loadedFor.current === selectedId || !versions) {
      return;
    }
    loadedFor.current = selectedId;
    const latest = versions.length > 0 ? versions[versions.length - 1] : null;
    if (!latest) {
      setNodes([]);
      setEdges([]);
      return;
    }
    setNodes(
      latest.definition.nodes.map((node, index) => ({
        id: node.key,
        type: "workflow" as const,
        position: {
          x: Number(node.position?.x ?? 80 + (index % 4) * 180),
          y: Number(node.position?.y ?? 60 + Math.floor(index / 4) * 120),
        },
        data: { label: node.key, nodeType: node.type as WorkflowNodeType },
      })),
    );
    setEdges(
      latest.definition.edges.map((edge) => ({
        id: `${edge.from}->${edge.to}`,
        source: edge.from,
        target: edge.to,
      })),
    );
  }, [selectedId, versions]);

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
          data: { label: id, nodeType },
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

  const handleCreate = (): void => {
    if (!newName.trim()) {
      setFeedback("请填写 Workflow 名");
      return;
    }
    createWorkflow.mutate(
      { name: newName.trim() },
      {
        onSuccess: (workflow: WorkflowResponse) => {
          setNewName("");
          loadedFor.current = null;
          setSelectedId(workflow.id);
          setFeedback("Workflow 已创建");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handleSave = (): void => {
    if (!selectedId) {
      setFeedback("请先选择或创建 Workflow");
      return;
    }
    if (nodes.length === 0) {
      setFeedback("画布为空，请先添加节点");
      return;
    }
    const payload: PublishWorkflowRequest = {
      nodes: nodes.map((node) => ({
        key: node.id,
        type: node.data.nodeType,
        // 条件编辑受白名单约束（不执行任意代码）；2b 仅占位空 config。
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
        onSuccess: (version) => setFeedback(`已保存为新版本 ${version.version}`),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Workflow Designer</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="workflow-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
        {/* 左：Workflow 列表 + 新建 */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Workflows</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2" data-testid="workflow-list">
                {isLoading ? (
                  <li className="text-sm text-muted-foreground">加载中…</li>
                ) : (workflows ?? []).length === 0 ? (
                  <li className="text-sm text-muted-foreground">暂无 Workflow</li>
                ) : (
                  (workflows ?? []).map((workflow) => (
                    <li key={workflow.id}>
                      <button
                        type="button"
                        data-testid={`workflow-item-${workflow.name}`}
                        onClick={() => {
                          loadedFor.current = null;
                          setSelectedId(workflow.id);
                        }}
                        className={
                          "w-full rounded-md border p-3 text-left transition-colors hover:bg-accent " +
                          (selectedId === workflow.id ? "border-primary" : "")
                        }
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">{workflow.name}</span>
                          <Badge variant="outline">{workflow.status}</Badge>
                        </div>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>新建 Workflow</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="workflow-name">名称</Label>
                <Input
                  id="workflow-name"
                  data-testid="workflow-name-input"
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                />
              </div>
              <Button
                size="sm"
                data-testid="workflow-create-submit"
                onClick={handleCreate}
                disabled={createWorkflow.isPending}
              >
                创建
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* 右：画布 + 工具栏 + 保存 */}
        <div className="space-y-3">
          <Card>
            <CardHeader>
              <CardTitle>节点工具栏</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2" data-testid="node-palette">
              {WORKFLOW_NODE_TYPES.map((nodeType) => (
                <Button
                  key={nodeType}
                  variant="outline"
                  size="sm"
                  data-testid={`add-node-${nodeType}`}
                  onClick={() => handleAddNode(nodeType)}
                >
                  + {nodeType}
                </Button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>画布</CardTitle>
              <Button
                size="sm"
                data-testid="workflow-save-submit"
                onClick={handleSave}
                disabled={publish.isPending}
              >
                保存为新版本
              </Button>
            </CardHeader>
            <CardContent>
              <div className="h-[420px] w-full rounded-md border" data-testid="workflow-canvas">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={NODE_TYPES}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={onConnect}
                  fitView
                >
                  <Background />
                  <Controls />
                </ReactFlow>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                节点 {nodes.length} · 连线 {edges.length}（连线即 `workflow_edge`）
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>版本</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2" data-testid="workflow-version-list">
                {(versions ?? []).length === 0 ? (
                  <li className="text-sm text-muted-foreground">暂无版本</li>
                ) : (
                  (versions ?? []).map((version) => (
                    <li
                      key={version.id}
                      className="flex items-center justify-between rounded-md border p-3"
                    >
                      <span className="text-sm">{version.version}</span>
                      <Badge variant="secondary">{version.status}</Badge>
                    </li>
                  ))
                )}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
