import { Activity, Globe, Loader2, ShieldCheck, Wifi } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTranslation } from "@/i18n";
import { API_BASE } from "@/lib/api";
import { cn } from "@/lib/cn";

/** 服务连通性检测结果。 */
type ConnectivityResult =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "ok"; latencyMs: number }
  | { state: "fail"; message: string };

/** 占位检测项（待后续接入真实探测）。 */
const PENDING_CHECKS = ["proxy", "hosts", "tcp", "packetLoss"] as const;

/**
 * 诊断工具弹窗（V0.4.5 B5 · F-25.6，Q10=a UI 先行）。
 *
 * - **总览**：「网络健康状况」徽标（未检测 = 灰）；
 * - **当前目标**三行：服务端点（应用 API base）/ 目标主机（host:port）/ 代理模式（直接连接占位）；
 * - **检测项五卡**：代理检测 / Hosts 解析 / TCP 连接延迟 / 丢包率 = 「待后续接入」禁用占位；
 *   **服务连通性 = 真实执行**：`fetch("<api-base>/health", { cache: "no-store" })` 计时，
 *   展示 ✓ 可达 + 延迟 ms / ✗ 不可达。
 */
export function DiagnosticsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [result, setResult] = useState<ConnectivityResult>({ state: "idle" });

  // 当前目标：服务端点取应用 API base；主机由 base 解析（相对路径 → 以当前源解析）。
  const endpoint = API_BASE;
  let host = "—";
  try {
    host = new URL(API_BASE, window.location.origin).host;
  } catch {
    // 解析失败保留占位。
  }

  /** 服务连通性检测（真实执行）：fetch `/health` 并计时。 */
  const runCheck = async (): Promise<void> => {
    setResult({ state: "checking" });
    const startedAt = performance.now();
    try {
      await fetch(`${API_BASE}/health`, { cache: "no-store" });
      setResult({ state: "ok", latencyMs: Math.round(performance.now() - startedAt) });
    } catch (error) {
      setResult({
        state: "fail",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="diagnostics-dialog"
        className="max-w-lg gap-0 overflow-hidden p-0"
      >
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle>{t("diagnostics.title")}</DialogTitle>
          <DialogDescription className="sr-only">{t("diagnostics.title")}</DialogDescription>
        </DialogHeader>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto p-6">
          {/* 总览：网络健康状况徽标 + 开始检测。 */}
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">{t("diagnostics.health")}</span>
              <Badge
                data-testid="diagnostics-health-badge"
                variant={result.state === "ok" ? "default" : "secondary"}
                className={cn(
                  result.state === "ok" &&
                    "bg-primary/15 text-primary hover:bg-primary/15 dark:bg-accent/20 dark:text-accent dark:hover:bg-accent/20",
                )}
              >
                {result.state === "ok"
                  ? t("diagnostics.health.ok")
                  : result.state === "fail"
                    ? t("diagnostics.health.fail")
                    : t("diagnostics.health.unknown")}
              </Badge>
            </div>
            <Button
              type="button"
              size="sm"
              data-testid="diagnostics-run"
              disabled={result.state === "checking"}
              onClick={() => void runCheck()}
            >
              {result.state === "checking" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
              {t("diagnostics.run")}
            </Button>
          </div>

          {/* 当前目标三行。 */}
          <dl className="space-y-2 rounded-lg border border-border bg-muted/30 px-4 py-3 text-xs">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">{t("diagnostics.target.endpoint")}</dt>
              <dd data-testid="diagnostics-endpoint" className="truncate font-mono text-foreground">
                {endpoint}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">{t("diagnostics.target.host")}</dt>
              <dd data-testid="diagnostics-host" className="truncate font-mono text-foreground">
                {host}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">{t("diagnostics.target.proxyMode")}</dt>
              <dd data-testid="diagnostics-proxy-mode" className="text-foreground">
                {t("diagnostics.target.proxyDirect")}
              </dd>
            </div>
          </dl>

          {/* 检测项五卡。 */}
          <div className="grid grid-cols-2 gap-2">
            {PENDING_CHECKS.map((key) => (
              <div
                key={key}
                data-testid={`diagnostics-check-${key}`}
                aria-disabled="true"
                className="flex flex-col gap-1 rounded-lg border border-dashed border-border px-3 py-2.5 opacity-70"
              >
                <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                  {key === "proxy" ? (
                    <Globe className="h-3.5 w-3.5 text-muted-foreground" />
                  ) : key === "hosts" ? (
                    <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
                  ) : key === "tcp" ? (
                    <Activity className="h-3.5 w-3.5 text-muted-foreground" />
                  ) : (
                    <Wifi className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                  {t(`diagnostics.check.${key}`)}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {t("diagnostics.check.pending")}
                </span>
              </div>
            ))}

            {/* 服务连通性（真实执行）。 */}
            <div
              data-testid="diagnostics-check-connectivity"
              className="flex flex-col gap-1 rounded-lg border border-border bg-card px-3 py-2.5"
            >
              <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                <Activity className="h-3.5 w-3.5 text-muted-foreground" />
                {t("diagnostics.check.connectivity")}
              </span>
              <span
                data-testid="diagnostics-connectivity-result"
                className={cn(
                  "text-[11px]",
                  result.state === "ok"
                    ? "text-primary dark:text-accent"
                    : result.state === "fail"
                      ? "text-destructive"
                      : "text-muted-foreground",
                )}
              >
                {result.state === "ok"
                  ? `✓ ${t("diagnostics.check.reachable", { ms: String(result.latencyMs) })}`
                  : result.state === "fail"
                    ? `✗ ${t("diagnostics.check.unreachable")}${result.message ? `（${result.message}）` : ""}`
                    : result.state === "checking"
                      ? t("diagnostics.check.checking")
                      : t("diagnostics.check.idle")}
              </span>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
