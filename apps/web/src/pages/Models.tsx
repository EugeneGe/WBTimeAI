import { useState } from "react";

import { CredentialForm } from "@/components/models/CredentialForm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCredentials, useProviderModels, useProviders } from "@/hooks/useModels";
import { cn } from "@/lib/cn";

/**
 * Models 页面（W7 / T1-34）。
 *
 * Provider 目录 + 模型目录 + 凭证**仅掩码**管理（前端**不请求 / 不展示明文**，C-07）。
 */
export function Models() {
  const { data: providers } = useProviders();
  const { data: credentials } = useCredentials();
  const [providerId, setProviderId] = useState<string | null>(null);
  const { data: models } = useProviderModels(providerId);

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Models</h1>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-[280px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>模型提供方</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1">
              {(providers ?? []).length === 0 ? (
                <li className="text-sm text-muted-foreground">暂无提供方</li>
              ) : (
                (providers ?? []).map((provider) => (
                  <li key={provider.id}>
                    <button
                      type="button"
                      data-testid={`provider-${provider.id}`}
                      className={cn(
                        "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-accent",
                        providerId === provider.id && "bg-accent",
                      )}
                      onClick={() => setProviderId(provider.id)}
                    >
                      <span className="truncate">{provider.name}</span>
                      <Badge variant={provider.status === "ACTIVE" ? "default" : "secondary"}>
                        {provider.status}
                      </Badge>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>模型目录</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>上下文</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {!providerId ? (
                    <TableRow>
                      <TableCell colSpan={3} className="text-sm text-muted-foreground">
                        请选择左侧提供方
                      </TableCell>
                    </TableRow>
                  ) : (models ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} className="text-sm text-muted-foreground">
                        暂无模型
                      </TableCell>
                    </TableRow>
                  ) : (
                    (models ?? []).map((model) => (
                      <TableRow key={model.id}>
                        <TableCell>{model.name}</TableCell>
                        <TableCell>{model.type}</TableCell>
                        <TableCell>{model.context_window ?? "—"}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <CredentialForm />

          <Card data-testid="credential-list">
            <CardHeader>
              <CardTitle>已有凭证（仅掩码）</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>提供方</TableHead>
                    <TableHead>类型</TableHead>
                    <TableHead>掩码值</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(credentials ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={3} className="text-sm text-muted-foreground">
                        暂无凭证
                      </TableCell>
                    </TableRow>
                  ) : (
                    (credentials ?? []).map((credential) => (
                      <TableRow key={credential.id}>
                        <TableCell>{credential.provider}</TableCell>
                        <TableCell>{credential.key_type}</TableCell>
                        <TableCell className="font-mono text-xs">
                          {credential.masked_value}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
