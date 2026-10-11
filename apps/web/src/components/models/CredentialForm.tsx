import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSaveCredential } from "@/hooks/useModels";
import { toApiError } from "@/lib/api";
import type { CredentialResponse } from "@/types";

/** 凭证录入表单选项。 */
export interface CredentialFormProps {
  /** 保存成功回调（返回**仅掩码**凭证）。 */
  onSaved?: (credential: CredentialResponse) => void;
}

/** API Key 类型选项。 */
const KEY_TYPES = ["api_key", "bearer", "oauth"] as const;

/**
 * 凭证录入表单（W7 / T1-34）。
 *
 * 🔴 **仅掩码**（C-07）：明文 `value` 仅在提交时传输一次，**不回显**；
 * 服务端返回并展示的仅 `masked_value`。前端**不请求明文**。
 */
export function CredentialForm({ onSaved }: CredentialFormProps) {
  const [provider, setProvider] = useState("");
  const [keyType, setKeyType] = useState<string>("api_key");
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState<CredentialResponse | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const saveCredential = useSaveCredential();

  const handleSubmit = (): void => {
    if (!provider.trim() || !value.trim()) {
      setFeedback("请填写提供方与密钥");
      return;
    }
    setFeedback(null);
    saveCredential.mutate(
      { provider: provider.trim(), key_type: keyType, value },
      {
        onSuccess: (credential) => {
          // 立即清空输入框中的明文，仅保留掩码展示。
          setValue("");
          setSaved(credential);
          setFeedback("凭证已保存（仅掩码回显）");
          onSaved?.(credential);
        },
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <Card data-testid="credential-form">
      <CardHeader>
        <CardTitle>凭证管理</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground" data-testid="credential-masked-note">
          凭证**仅掩码**：明文提交后不落前端、不回显；页面只展示 <code>masked_value</code>。
        </p>
        <div className="space-y-2">
          <Label htmlFor="credential-provider">提供方</Label>
          <Input
            id="credential-provider"
            data-testid="credential-provider-input"
            value={provider}
            placeholder="openai / anthropic / …"
            onChange={(event) => setProvider(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="credential-key-type">密钥类型</Label>
          <select
            id="credential-key-type"
            data-testid="credential-key-type-select"
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={keyType}
            onChange={(event) => setKeyType(event.target.value)}
          >
            {KEY_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="credential-value">密钥（明文，仅传输）</Label>
          <Input
            id="credential-value"
            data-testid="credential-value-input"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>
        {feedback ? (
          <p className="text-sm text-muted-foreground" data-testid="credential-feedback">
            {feedback}
          </p>
        ) : null}
        {saved ? (
          <div className="flex items-center gap-2" data-testid="credential-masked-value">
            <span className="text-xs text-muted-foreground">掩码：</span>
            <Badge variant="secondary">{saved.masked_value}</Badge>
          </div>
        ) : null}
        <Button
          size="sm"
          data-testid="credential-submit"
          onClick={handleSubmit}
          disabled={saveCredential.isPending}
        >
          保存凭证
        </Button>
      </CardContent>
    </Card>
  );
}
