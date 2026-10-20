// ---------------------------------------------------------------------------
// 路由表（D-UI体验优化波 · WS-I · DU-9）
//
// 施工方案 §2T.1 + Phase 1 / W7 T1-34 + Phase 2a / W3 T2-18。
//
// 分层加载策略（裁定 §1 WS-I / §7 P2 风险）：
//   - **同步挂载**：`RequireAuth` 与 `App`（`AppLayout` 外壳）保持静态导入，
//     避免整壳被 Suspense 抖动；外壳常驻，仅页面内容随分包加载切换。
//   - **懒加载**：全部 19 个渲染页经 `React.lazy` 按需分包，`<Suspense>` 兜底为
//     {@link RouteFallback}；页面均为**具名导出**，故经 `.then` 适配为 `default`。
//     另有 5 条重定向路由为**同步** `<Navigate>`，不参与懒加载；企业页 `Enterprise`
//     为 `[U-9]` 预留空槽（声明已注释、未启用），故不在上述 19 个之列。
//   - 路由结构保留（B-02 例外：根路径 index 改重定向 `/chat`，工作台迁 `/workbench`），
//     其余路径零变更，仅替换元素的加载方式。
//
// 守护：`/login` `/register` 公开；其余经 {@link RequireAuth} 守护；
// 需权动作再包 `RequirePermission`（在页面内部按权限码守护）。
// ---------------------------------------------------------------------------
import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";

import { App } from "@/App";
import { RouteFallback } from "@/components/common/RouteFallback";
import { RequireAuth } from "@/components/guards/RequireAuth";

// ---------------------------------------------------------------------------
// [U-9] 企业设置页路由预留槽位（V0.5 W3 接入；当前零行为变化）
//
// 拍板口径（2026-10-15）：**预留 + 默认隐藏**——社区版路由表保留懒加载空槽，
// 待 V0.5 W3 企业设置页就绪后启用（见 `docs/施工方案/V0.5/00-开工前架构裁定.md`
// `DD-7` / §6 `U-9`）。
//
// 落点对齐 `DD-7`：企业页落 `apps/web/src/pages/enterprise/*`（**不新建 `features/` 层**）。
//
// W3 启用指引：
//   ① 解除下方 `const Enterprise = lazy(...)` 注释；
//   ② 将下方 `[U-9]` 挂载位改为 `{ path: ENTERPRISE_ROUTE_SLOT.path, element: page(<Enterprise />) }`；
//   ③ 将 `ENTERPRISE_ROUTE_SLOT.shipped` 置 `true`，并放开 `Rail.tsx` 中
//      `{ key: "enterprise", enabled: false }` → `enabled: true`。
// ---------------------------------------------------------------------------

/**
 * 企业设置页路由预留槽位常量（防误删锚点）。
 *
 * `shipped === false` 表示**空槽（未启用）**；隐藏态测试断言其恒为 `false`。
 * `path` 与 `Rail.tsx` 预留项 `to` 对齐（`/enterprise`）。
 */
export const ENTERPRISE_ROUTE_SLOT = { path: "enterprise", shipped: false } as const;

// -- 页面级懒加载（具名导出 → React.lazy 的 default 适配） -------------------
const Login = lazy(() => import("@/pages/Login").then((m) => ({ default: m.Login })));
const Register = lazy(() => import("@/pages/Register").then((m) => ({ default: m.Register })));
const User = lazy(() => import("@/pages/User").then((m) => ({ default: m.User })));
const Workspace = lazy(() => import("@/pages/Workspace").then((m) => ({ default: m.Workspace })));
const Chat = lazy(() => import("@/pages/Chat").then((m) => ({ default: m.Chat })));
const Agents = lazy(() => import("@/pages/Agents").then((m) => ({ default: m.Agents })));
const AgentDetail = lazy(() =>
  import("@/pages/AgentDetail").then((m) => ({ default: m.AgentDetail })),
);
const Tools = lazy(() => import("@/pages/Tools").then((m) => ({ default: m.Tools })));
const Projects = lazy(() => import("@/pages/Projects").then((m) => ({ default: m.Projects })));
const Tasks = lazy(() => import("@/pages/Tasks").then((m) => ({ default: m.Tasks })));
const RemoteTasks = lazy(() =>
  import("@/pages/RemoteTasks").then((m) => ({ default: m.RemoteTasks })),
);
// -- W10 / T2-49：审批中心（`/approvals`；`GET/POST /approvals/*` 四端点）。
const Approvals = lazy(() => import("@/pages/Approvals").then((m) => ({ default: m.Approvals })));
// [U-9] 旧设置页改为路由不可达（V0.4.5 B5 · F-26.5）：懒加载位删除，源文件与单测保留。
const SettingsWindow = lazy(() =>
  import("@/pages/SettingsWindow").then((m) => ({ default: m.SettingsWindow })),
);
const AgentStudio = lazy(() =>
  import("@/pages/studio/AgentStudio").then((m) => ({ default: m.AgentStudio })),
);
const AgentVersions = lazy(() =>
  import("@/pages/studio/AgentVersions").then((m) => ({ default: m.AgentVersions })),
);
const Evaluation = lazy(() =>
  import("@/pages/studio/Evaluation").then((m) => ({ default: m.Evaluation })),
);
const WorkflowDesigner = lazy(() =>
  import("@/pages/studio/WorkflowDesigner").then((m) => ({ default: m.WorkflowDesigner })),
);
const KnowledgeManager = lazy(() =>
  import("@/pages/studio/KnowledgeManager").then((m) => ({ default: m.KnowledgeManager })),
);
const MemoryView = lazy(() =>
  import("@/pages/studio/MemoryView").then((m) => ({ default: m.MemoryView })),
);
// [U-9] 企业设置页懒加载空槽（V0.5 W3 启用；当前不导入以避免空引用）：
// const Enterprise = lazy(() => import("@/pages/enterprise/Enterprise").then((m) => ({ default: m.Enterprise })));

/**
 * 路由级懒加载兜底：页面分包就绪前渲染 {@link RouteFallback}。
 *
 * 仅包裹**页面元素**；外壳（`RequireAuth` / `App`）保持同步，避免整壳重挂。
 */
function page(node: ReactNode): ReactNode {
  return <Suspense fallback={<RouteFallback />}>{node}</Suspense>;
}

/**
 * 受保护子路由表（即 `/` 的 `children`）。
 *
 * **B-02（V0.4.6 BugFix）落地页裁定**：打开根路径 / 刚进入应用应落在**主窗口 `/chat`**——
 * - `index` 由「渲染工作台（`pages/User.tsx`）」改为 **`<Navigate to="/chat" replace />`**；
 * - 工作台迁至**独立路径 `/workbench`**（`page(<User />)`），由 Rail「工作台」项与直接
 *   URL 可达，页面本身零改动。
 *
 * 导出供 `matchRoutes` / 重定向行为单测复用（`src/__tests__/router.test.tsx`）。
 */
// 本文件导出路由表常量（非组件），fast-refresh 规则不适用（与既有 ENTERPRISE_ROUTE_SLOT 同）。
// eslint-disable-next-line react-refresh/only-export-components
export const APP_ROUTES: RouteObject[] = [
  // -- B-02：根路径 → 主窗口（`/chat`），`replace` 避免返回键回落到空落地页。
  { index: true, element: <Navigate to="/chat" replace /> },
  // -- B-02：工作台（原 index 页）迁至 `/workbench`。
  { path: "workbench", element: page(<User />) },
  { path: "workspace", element: page(<Workspace />) },
  { path: "chat", element: page(<Chat />) },
  { path: "agents", element: page(<Agents />) },
  { path: "agents/:agentId", element: page(<AgentDetail />) },
  // -- B-09：旧 `/models` 页下线（能力并入 设置·模型）→ 兼容重定向到工作台。
  { path: "models", element: <Navigate to="/workbench" replace /> },
  { path: "tools", element: page(<Tools />) },
  // -- Phase 2c / W10（T2-50）：Projects / Tasks（2c 子集）
  { path: "projects", element: page(<Projects />) },
  { path: "tasks", element: page(<Tasks />) },
  // -- W10 / T2-49：审批中心（待办列表 / 详情 / 通过 / 驳回；仅要求登录，不需额外权限码）
  { path: "approvals", element: page(<Approvals />) },
  // -- Phase 2 / R4（T2-62）：远程工作台（提交 / 跟踪 / 审阅 / Apply / Push）
  //    F-15（V0.4.5 B3）：「远程任务」已**移出 Rail**，但**路由保留**——
  //    经工作台快捷入口（`pages/User.tsx`）/ 侧栏 / 直接 URL 仍可达。
  { path: "remote-tasks", element: page(<RemoteTasks />) },
  // -- Phase 2c / W8（T2-41）：Agent Studio 主框架（左九分区 + 右配置/预览）
  { path: "studio", element: page(<AgentStudio />) },
  { path: "studio/agents/:agentId", element: page(<AgentVersions />) },
  // -- Phase 2c / W8（T2-44）：Marketplace（导入导出）
  //    V0.4.5 B4 · F-22.3：**旧路由重定向** → 智能页「技能」Tab（源文件与单测保留，改为路由不可达）。
  { path: "studio/marketplace", element: <Navigate to="/agents?tab=skills" replace /> },
  // -- Phase 2c / W9（T2-47）：Evaluation（任务集 / 批量执行 / 回归对比）
  //    F-15（V0.4.5 B3）：「评估中心」已**移出 Rail**，但**路由保留**（可达性不变）。
  { path: "studio/evaluation", element: page(<Evaluation />) },
  // -- Phase 2a / W3（T2-18）：Studio 子集（Skill Builder / MCP Manager）
  //    V0.4.5 B4 · F-22.3：**旧路由重定向** → 智能页对应 Tab（源文件与单测保留，改为路由不可达）。
  { path: "studio/skills", element: <Navigate to="/agents?tab=skills" replace /> },
  { path: "studio/mcp", element: <Navigate to="/agents?tab=connectors" replace /> },
  // -- Phase 2b / W6（T2-35）：Workflow / Knowledge / Memory
  { path: "studio/workflows", element: page(<WorkflowDesigner />) },
  { path: "studio/knowledge", element: page(<KnowledgeManager />) },
  { path: "studio/memory", element: page(<MemoryView />) },
  // [U-9] 企业设置页挂载位（预留空槽）：W3 启用时解除以下注释并替换为实际元素；
  //       槽位以 ENTERPRISE_ROUTE_SLOT 常量对齐，路径 `/enterprise`（对齐 DD-7）。
  // { path: ENTERPRISE_ROUTE_SLOT.path, element: page(<Enterprise />) },
];

/**
 * 应用路由表（`createBrowserRouter`）。受保护子路由见 {@link APP_ROUTES}。
 */
// 本文件导出路由表常量（非组件），fast-refresh 规则不适用（与上方 APP_ROUTES 同）。
// eslint-disable-next-line react-refresh/only-export-components
export const router = createBrowserRouter([
  { path: "/login", element: page(<Login />) },
  { path: "/register", element: page(<Register />) },
  {
    path: "/",
    element: (
      <RequireAuth>
        <App />
      </RequireAuth>
    ),
    children: APP_ROUTES,
  },
  // -- V0.4.5 B5 · F-26.5（Q12 拍板）：设置**独立窗口路由**（顶层，不经 AppLayout 外壳）——
  //    桌面壳「独立设置窗口」加载 `/settings?section=<key>`；旧壳内 `/settings` 页面路由
  //    被**本路由替代**（原 `pages/Settings.tsx` 源文件与单测保留，改为路由不可达）。
  {
    path: "/settings",
    element: <RequireAuth>{page(<SettingsWindow />)}</RequireAuth>,
  },
]);
