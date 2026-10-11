import {
  Bot,
  BookOpen,
  Brain,
  Cpu,
  FolderKanban,
  LayoutGrid,
  ListChecks,
  LogOut,
  MessagesSquare,
  Server,
  Settings as SettingsIcon,
  Sparkles,
  User as UserIcon,
  Workflow,
  Wrench,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { usePermission } from "@/lib/permission";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { to: "/", label: "用户", icon: UserIcon, permission: null },
  { to: "/workspace", label: "工作区", icon: LayoutGrid, permission: null },
  { to: "/chat", label: "Chat", icon: MessagesSquare, permission: null },
  { to: "/agents", label: "Agents", icon: Bot, permission: null },
  { to: "/models", label: "Models", icon: Cpu, permission: null },
  { to: "/tools", label: "Tools", icon: Wrench, permission: null },
  // -- Phase 2c / W10（T2-50）：Projects / Tasks
  { to: "/projects", label: "Projects", icon: FolderKanban, permission: null },
  { to: "/tasks", label: "Tasks", icon: ListChecks, permission: null },
  // -- Phase 2a / W3（T2-18）：Studio 子集
  { to: "/studio/skills", label: "Skills", icon: Sparkles, permission: null },
  { to: "/studio/mcp", label: "MCP", icon: Server, permission: null },
  // -- Phase 2b / W6（T2-35）：Workflow / Knowledge / Memory
  { to: "/studio/workflows", label: "Workflows", icon: Workflow, permission: null },
  { to: "/studio/knowledge", label: "Knowledge", icon: BookOpen, permission: null },
  { to: "/studio/memory", label: "Memory", icon: Brain, permission: null },
  { to: "/settings", label: "设置", icon: SettingsIcon, permission: null },
] as const;

/** 顶部导航（依 `usePermission()` 决定项可见性）+ 登出。 */
export function Navbar() {
  const { logout } = useAuth();
  const { can } = usePermission();

  const visibleItems = NAV_ITEMS.filter((item) => item.permission === null || can(item.permission));

  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <div className="flex items-center gap-1">
          <span className="mr-4 text-base font-semibold">Astra AI</span>
          <nav className="flex items-center gap-1">
            {visibleItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
                    isActive && "bg-accent text-accent-foreground",
                  )
                }
                end={item.to === "/"}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          <LogOut className="h-4 w-4" />
          登出
        </Button>
      </div>
    </header>
  );
}
