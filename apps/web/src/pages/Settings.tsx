import { useEffect, useState } from "react";

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
import {
  useCredentials,
  useFeatureFlags,
  usePersonalSettings,
  useSaveCredential,
  useSystemSettings,
  useUpdatePersonalSettings,
} from "@/hooks/useSettings";
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
            <p className="text-sm text-muted-foreground">加载中…</p>
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
              <Button size="sm" onClick={handleSaveCredential} disabled={saveCredential.isPending}>
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

      {!can("settings:update") ? (
        <p className="text-xs text-muted-foreground">无 `settings:update` 权限，仅可查看。</p>
      ) : null}
    </div>
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
