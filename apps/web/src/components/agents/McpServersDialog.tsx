import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useMcpServers } from "@/hooks/useMcp";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";

/** 展示用 MCP 配置文件路径（骨架；不落库）。 */
const MCP_CONFIG_PATH = "~/.wbtime-ai/mcp.json";

/** JSON 编辑态初始模板（`mcpServers` 结构）。 */
const DEFAULT_MCP_JSON = `{
  "mcpServers": {}
}`;

/** MCP 服务管理弹窗属性。 */
export interface McpServersDialogProps {
  /** 是否打开。 */
  open: boolean;
  /** 开合回调（radix 内建 Esc / 点击外部触发）。 */
  onOpenChange: (open: boolean) => void;
}

/** 弹窗内部态：列表 ↔ JSON 编辑。 */
type DialogMode = "list" | "edit";

/**
 * MCP 服务管理弹窗（V0.4.5 B4 · F-22.5 **骨架**）。
 *
 * - **列表态**（ref23）：我的 MCP（`useMcpServers` 只读）+ 启用开关（本地态）+ 添加 MCP + MCP Hub；
 * - **JSON 编辑态**（ref24）：`mcpServers` 配置编辑（`<textarea>`）+ 配置文件路径 + 返回 / 取消 / 保存；
 *   **保存仅校验 JSON 合法性**并本地演示（**不落库**，登记遗留）。
 *
 * `data-testid`：`agents-mcp-dialog` / `agents-mcp-list` / `agents-mcp-add` / `agents-mcp-json-editor`
 * / `agents-mcp-json-save` / `agents-mcp-json-back`。
 */
export function McpServersDialog({ open, onOpenChange }: McpServersDialogProps) {
  const { t } = useTranslation();
  const { data: servers } = useMcpServers();
  const [mode, setMode] = useState<DialogMode>("list");
  const [json, setJson] = useState(DEFAULT_MCP_JSON);
  const [error, setError] = useState<string | null>(null);
  // 启用态（本地态占位，不落库）。
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>({});

  const list = servers ?? [];
  const enabledCount = list.filter((server) => enabledMap[server.id] ?? true).length;

  // 每次打开复位到列表态。
  useEffect(() => {
    if (open) {
      setMode("list");
      setError(null);
    }
  }, [open]);

  const backToList = (): void => {
    setMode("list");
    setError(null);
  };

  /** 保存：仅校验 JSON 合法性（本地演示，不落库）。 */
  const handleSave = (): void => {
    try {
      const parsed: unknown = JSON.parse(json.trim() || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setError("配置需为 JSON 对象");
        return;
      }
    } catch {
      setError("JSON 格式不正确");
      return;
    }
    setError(null);
    setMode("list");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="agents-mcp-dialog" className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("agents.mcp.title")}</DialogTitle>
          <DialogDescription>{t("agents.mcp.subtitle")}</DialogDescription>
        </DialogHeader>

        {mode === "list" ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-foreground">
                {t("agents.mcp.myList", { count: String(list.length) })}
              </span>
              <span className="text-xs text-muted-foreground">
                {t("agents.mcp.enabledCount", { count: String(enabledCount) })}
              </span>
            </div>

            <ul data-testid="agents-mcp-list" className="max-h-[240px] space-y-2 overflow-auto">
              {list.length === 0 ? (
                <li className="text-sm text-muted-foreground">—</li>
              ) : (
                list.map((server) => {
                  const active = enabledMap[server.id] ?? true;
                  return (
                    <li
                      key={server.id}
                      data-testid={`agents-mcp-item-${server.id}`}
                      className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
                    >
                      <span className="truncate text-sm text-foreground">{server.name}</span>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={active}
                        aria-label={server.name}
                        data-testid={`agents-mcp-toggle-${server.id}`}
                        onClick={() =>
                          setEnabledMap((previous) => ({
                            ...previous,
                            [server.id]: !(previous[server.id] ?? true),
                          }))
                        }
                        className={cn(
                          "relative h-5 w-9 flex-none rounded-full transition-colors",
                          active ? "bg-primary" : "bg-muted",
                        )}
                      >
                        <span
                          className={cn(
                            "absolute top-0.5 h-4 w-4 rounded-full bg-background transition-all",
                            active ? "left-[18px]" : "left-0.5",
                          )}
                        />
                      </button>
                    </li>
                  );
                })
              )}
            </ul>

            <div className="flex items-center gap-2">
              <Button size="sm" data-testid="agents-mcp-add" onClick={() => setMode("edit")}>
                {t("agents.mcp.add")}
              </Button>
              <Button size="sm" variant="outline" data-testid="agents-mcp-hub">
                {t("agents.mcp.hub")}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="agents-mcp-config-path">{t("agents.mcp.configPath")}</Label>
              <p
                id="agents-mcp-config-path"
                className="font-mono text-xs text-muted-foreground"
                data-testid="agents-mcp-config-path"
              >
                {MCP_CONFIG_PATH}
              </p>
            </div>

            <textarea
              data-testid="agents-mcp-json-editor"
              value={json}
              spellCheck={false}
              onChange={(event) => setJson(event.target.value)}
              className="min-h-[180px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
            />

            {error ? (
              <p className="text-sm text-destructive" data-testid="agents-mcp-json-error">
                {error}
              </p>
            ) : null}

            <div className="flex items-center justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                data-testid="agents-mcp-json-back"
                onClick={backToList}
              >
                {t("agents.mcp.back")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button size="sm" data-testid="agents-mcp-json-save" onClick={handleSave}>
                {t("common.save")}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
