import { useEffect, useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { PageContainer } from "@/components/layout/PageContainer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCredentials,
  useFeatureFlags,
  usePersonalSettings,
  useSaveCredential,
  useSystemSettings,
  useUpdatePersonalSettings,
} from "@/hooks/useSettings";
import { useDesktopSettings } from "@/hooks/useDesktopSettings";
import { useRuntimeStatus } from "@/hooks/useRuntimeStatus";
import { toApiError } from "@/lib/api";
import { usePermission } from "@/lib/permission";

/** 设置页：系统 / 个人设置 + API Key 保存（`settings:update`）+ 凭证列表（仅掩码）+ Feature Flag 观测。 */
export function Settings() {
  const { can } = usePermission();
  const system = useSystemSettings();
  const personal = usePersonalSettings();
  const credentials = useCredentials();
  const features = useFeatureFlags();
  const updatePersonal = useUpdatePersonalSettings();
  const saveCredential = useSaveCredential();

  const [displayName, setDisplayName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [value, setValue] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (personal.data) {
      setDisplayName(personal.data.display_name ?? "");
    }
  }, [personal.data]);

  const handleSavePersonal = () => {
    setFeedback(null);
    updatePersonal.mutate(
      { display_name: displayName || null },
      {
        onSuccess: () => setFeedback("个人设置已保存"),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const handleSaveCredential = () => {
    if (!provider.trim() || !value.trim()) {
      setFeedback("请填写提供方与密钥");
      return;
    }
    setFeedback(null);
    saveCredential.mutate(
      { provider: provider.trim(), value: value.trim() },
      {
        onSuccess: () => {
          setValue("");
          setFeedback("凭证已保存（仅掩码存储）");
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <PageContainer>
      <div className="space-y-6">
        {feedback ? <p className="text-sm text-muted-foreground">{feedback}</p> : null}

        <Card>
          <CardHeader>
            <CardTitle>系统设置</CardTitle>
          </CardHeader>
          <CardContent>
            {system.data ? (
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <InfoItem label="运行模式" value={system.data.mode} />
                <InfoItem label="应用名" value={system.data.app_name} />
                <InfoItem label="版本" value={system.data.app_version} />
              </dl>
            ) : (
              <div className="space-y-2" data-testid="settings-system-loading">
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-4 w-32" />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>个人设置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="display-name">显示名</Label>
              <Input
                id="display-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </div>
            <Button size="sm" onClick={handleSavePersonal} disabled={updatePersonal.isPending}>
              保存
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>API Key</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <RequirePermission code="settings:update">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-[200px_1fr_auto] sm:items-end">
                <div className="space-y-1.5">
                  <Label htmlFor="provider">提供方</Label>
                  <Input
                    id="provider"
                    value={provider}
                    onChange={(event) => setProvider(event.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="value">密钥</Label>
                  <Input
                    id="value"
                    type="password"
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                  />
                </div>
                <Button
                  size="sm"
                  onClick={handleSaveCredential}
                  disabled={saveCredential.isPending}
                >
                  保存
                </Button>
              </div>
            </RequirePermission>

            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>提供方</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>掩码值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(credentials.data ?? []).map((credential) => (
                  <TableRow key={credential.id}>
                    <TableCell>{credential.provider}</TableCell>
                    <TableCell>{credential.key_type}</TableCell>
                    <TableCell>{credential.masked_value}</TableCell>
                  </TableRow>
                ))}
                {(credentials.data ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      暂无凭证
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Feature Flags（只读观测）</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {features.data
              ? Object.entries(features.data.flags).map(([name, enabled]) => (
                  <Badge key={name} variant={enabled ? "default" : "secondary"}>
                    {name}: {enabled ? "on" : "off"}
                  </Badge>
                ))
              : null}
          </CardContent>
        </Card>

        {/* 桌面设置 · 数据目录（仅桌面壳内 `window.wbtimeAiDesktop` 存在时渲染；纯 Web 自动隐藏）。 */}
        <DesktopDataDirCard />

        {/* 桌面设置 · 便携运行时（T6；同上，仅桌面壳内渲染）。 */}
        <DesktopRuntimeCard />

        {!can("settings:update") ? (
          <p className="text-xs text-muted-foreground">无 `settings:update` 权限，仅可查看。</p>
        ) : null}
      </div>
    </PageContainer>
  );
}

/**
 * 桌面设置 · 数据目录 Card（T4）。
 *
 * - **仅** `window.wbtimeAiDesktop` 存在（桌面壳内）时渲染；纯 Web 部署返回 `null`；
 * - 渲染层做**即时提示**（绝对路径 / 拒绝 UNC），但**不替代主进程校验**：
 *   权威判定在 `SettingsStore.update → validateDataDir`，非法值经 IPC 拒绝并回显；
 * - 「恢复默认」= 清空字段（`dataDir=""`）→ 后端回退 `~/.wbtime-ai`；重启壳后生效。
 */
function DesktopDataDirCard() {
  const { available, settings, loading, error, save } = useDesktopSettings();
  const [value, setValue] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  useEffect(() => {
    if (settings) {
      setValue(settings.dataDir);
    }
  }, [settings]);

  if (!available) {
    return null;
  }

  const handleSave = async () => {
    setHint(null);
    setFeedback(null);
    const trimmed = value.trim();
    // 渲染层即时提示（不替代主进程校验）。
    if (trimmed.startsWith("\\\\") || trimmed.startsWith("//")) {
      setHint("不支持网络路径（UNC），请使用本地磁盘绝对路径");
      return;
    }
    if (trimmed !== "" && !/^(?:[A-Za-z]:[\\/]|\/)/.test(trimmed)) {
      setHint("请输入绝对路径（如 D:\\WBTimeAIData）");
      return;
    }
    const next = await save({ dataDir: trimmed });
    if (next) {
      setValue(next.dataDir);
      setFeedback(
        next.dataDir === ""
          ? "已恢复默认（~/.wbtime-ai）"
          : `已保存，重启桌面壳后生效：${next.dataDir}`,
      );
    }
  };

  const handleReset = async () => {
    setHint(null);
    setFeedback(null);
    const next = await save({ dataDir: "" });
    if (next) {
      setValue("");
      setFeedback("已恢复默认（~/.wbtime-ai）");
    }
  };

  return (
    <Card data-testid="desktop-data-dir-card">
      <CardHeader>
        <CardTitle>桌面设置 · 数据目录</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="desktop-data-dir">数据目录（绝对路径）</Label>
          <Input
            id="desktop-data-dir"
            data-testid="desktop-data-dir-input"
            value={value}
            placeholder="留空 = 使用默认 ~/.wbtime-ai"
            disabled={loading}
            onChange={(event) => setValue(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            修改后需<strong>重启桌面壳</strong>生效；留空或「恢复默认」回退 ~/.wbtime-ai。
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            data-testid="desktop-data-dir-save"
            onClick={() => void handleSave()}
            disabled={loading}
          >
            保存
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid="desktop-data-dir-reset"
            onClick={() => void handleReset()}
            disabled={loading}
          >
            恢复默认
          </Button>
        </div>
        {hint ? <p className="text-sm text-destructive">{hint}</p> : null}
        {error ? (
          <p className="text-sm text-destructive" data-testid="desktop-data-dir-error">
            主进程校验未通过：{error}
          </p>
        ) : null}
        {feedback ? (
          <p className="text-sm text-muted-foreground" data-testid="desktop-data-dir-feedback">
            {feedback}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * 桌面设置 · 便携运行时 Card（T6）。
 *
 * - **仅** `window.wbtimeAiDesktop` 存在（桌面壳内）时渲染；纯 Web 部署返回 `null`；
 * - 显示解压阶段 / 进度（字节·百分比）+ 取消 / 重试（状态由主进程 IPC 实时推送）；
 * - 就绪后 `bundled` 档后端可用（无需用户自装 Python/wbtime-ai）。
 */
function DesktopRuntimeCard() {
  const { available, status, error, install, cancel } = useRuntimeStatus();

  if (!available) {
    return null;
  }

  const phase = status?.phase ?? "idle";
  const total = status?.totalBytes ?? 0;
  const done = status?.extractedBytes ?? 0;
  const busy = phase === "checking" || phase === "extracting";
  const percent =
    phase === "done" ? 100 : total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const mb = (n: number): string => (n / 1048576).toFixed(1);
  const labels: Record<string, string> = {
    idle: "未安装",
    checking: "校验中",
    extracting: "解压中",
    done: "已就绪",
    cancelled: "已取消",
    error: "失败",
  };

  return (
    <Card data-testid="desktop-runtime-card">
      <CardHeader>
        <CardTitle>桌面设置 · 便携运行时</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm" data-testid="desktop-runtime-phase">
          {labels[phase] ?? phase}
          {status?.detail ? (
            <span className="text-muted-foreground">（{status.detail}）</span>
          ) : null}
        </p>
        <div
          className="h-2 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
        </div>
        {phase === "extracting" && total > 0 ? (
          <p className="text-xs text-muted-foreground" data-testid="desktop-runtime-progress">
            {mb(done)} / {mb(total)} MB（{percent}%）
          </p>
        ) : null}
        {status?.runtimeDir ? (
          <p className="text-xs text-muted-foreground break-all">目录：{status.runtimeDir}</p>
        ) : null}
        <div className="flex gap-2">
          <Button
            size="sm"
            data-testid="desktop-runtime-retry"
            onClick={() => void install()}
            disabled={busy}
          >
            重试 / 安装
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid="desktop-runtime-cancel"
            onClick={() => void cancel()}
            disabled={!busy}
          >
            取消
          </Button>
        </div>
        {error ? (
          <p className="text-sm text-destructive" data-testid="desktop-runtime-error">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}
