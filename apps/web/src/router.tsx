import { createBrowserRouter } from "react-router-dom";

import { App } from "@/App";
import { RequireAuth } from "@/components/guards/RequireAuth";
import { AgentDetail } from "@/pages/AgentDetail";
import { Agents } from "@/pages/Agents";
import { Chat } from "@/pages/Chat";
import { Login } from "@/pages/Login";
import { Models } from "@/pages/Models";
import { Projects } from "@/pages/Projects";
import { Register } from "@/pages/Register";
import { Settings } from "@/pages/Settings";
import { AgentStudio } from "@/pages/studio/AgentStudio";
import { AgentVersions } from "@/pages/studio/AgentVersions";
import { Evaluation } from "@/pages/studio/Evaluation";
import { KnowledgeManager } from "@/pages/studio/KnowledgeManager";
import { Marketplace } from "@/pages/studio/Marketplace";
import { McpManager } from "@/pages/studio/McpManager";
import { MemoryView } from "@/pages/studio/MemoryView";
import { SkillBuilder } from "@/pages/studio/SkillBuilder";
import { WorkflowDesigner } from "@/pages/studio/WorkflowDesigner";
import { Tasks } from "@/pages/Tasks";
import { Tools } from "@/pages/Tools";
import { User } from "@/pages/User";
import { Workspace } from "@/pages/Workspace";

/**
 * 路由表（施工方案 §2T.1 + Phase 1 / W7 T1-34 + Phase 2a / W3 T2-18）。
 *
 * - `/login` `/register` 公开；
 * - `/`(User) `/workspace` `/settings` `/chat` `/agents` `/agents/:agentId`
 *   `/models` `/tools` `/projects` `/tasks` `/studio` `/studio/agents/:agentId`
 *   `/studio/marketplace`
 *   `/studio/skills` `/studio/mcp`
 *   `/studio/workflows` `/studio/knowledge` `/studio/memory` 受 {@link RequireAuth} 守护；
 * - 需权动作再包 `RequirePermission`（在页面内部按权限码守护）。
 */
export const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/register", element: <Register /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <App />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <User /> },
      { path: "workspace", element: <Workspace /> },
      { path: "chat", element: <Chat /> },
      { path: "agents", element: <Agents /> },
      { path: "agents/:agentId", element: <AgentDetail /> },
      { path: "models", element: <Models /> },
      { path: "tools", element: <Tools /> },
      // -- Phase 2c / W10（T2-50）：Projects / Tasks（2c 子集）
      { path: "projects", element: <Projects /> },
      { path: "tasks", element: <Tasks /> },
      // -- Phase 2c / W8（T2-41）：Agent Studio 主框架（左九分区 + 右配置/预览）
      { path: "studio", element: <AgentStudio /> },
      { path: "studio/agents/:agentId", element: <AgentVersions /> },
      // -- Phase 2c / W8（T2-44）：Marketplace（导入导出）
      { path: "studio/marketplace", element: <Marketplace /> },
      // -- Phase 2c / W9（T2-47）：Evaluation（任务集 / 批量执行 / 回归对比）
      { path: "studio/evaluation", element: <Evaluation /> },
      // -- Phase 2a / W3（T2-18）：Studio 子集（Skill Builder / MCP Manager）
      { path: "studio/skills", element: <SkillBuilder /> },
      { path: "studio/mcp", element: <McpManager /> },
      // -- Phase 2b / W6（T2-35）：Workflow / Knowledge / Memory
      { path: "studio/workflows", element: <WorkflowDesigner /> },
      { path: "studio/knowledge", element: <KnowledgeManager /> },
      { path: "studio/memory", element: <MemoryView /> },
      { path: "settings", element: <Settings /> },
    ],
  },
]);
