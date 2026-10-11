import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";

import { CreateAgentWizard } from "@/components/agents/CreateAgentWizard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAgents } from "@/hooks/useAgents";

/**
 * Agents 列表页（W7 / T1-33）。
 *
 * 列表 + 创建入口（四步向导：选择模型 → 配置 Prompt → 选择 Tool → 绑定 Workspace）。
 * 服务端数据走 TanStack Query。
 */
export function Agents() {
  const navigate = useNavigate();
  const { data: agents, isLoading } = useAgents();
  const [showWizard, setShowWizard] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Agents</h1>
        <Button size="sm" data-testid="toggle-wizard" onClick={() => setShowWizard((v) => !v)}>
          <Plus className="h-4 w-4" />
          创建 Agent
        </Button>
      </div>

      {showWizard ? (
        <CreateAgentWizard
          onCreated={(agent) => {
            setShowWizard(false);
            navigate(`/agents/${agent.id}`);
          }}
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>全部 Agent</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>名称</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>当前版本</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-sm text-muted-foreground">
                    加载中…
                  </TableCell>
                </TableRow>
              ) : (agents ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-sm text-muted-foreground">
                    暂无 Agent
                  </TableCell>
                </TableRow>
              ) : (
                (agents ?? []).map((agent) => (
                  <TableRow key={agent.id} data-testid={`agent-row-${agent.id}`}>
                    <TableCell>
                      <Link
                        className="text-primary underline-offset-4 hover:underline"
                        to={`/agents/${agent.id}`}
                      >
                        {agent.name}
                      </Link>
                    </TableCell>
                    <TableCell>{agent.type}</TableCell>
                    <TableCell>
                      <Badge variant={agent.status === "ACTIVE" ? "default" : "secondary"}>
                        {agent.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {agent.current_version_id ?? "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
