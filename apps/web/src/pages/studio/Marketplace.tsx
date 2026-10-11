import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { RequirePermission } from "@/components/guards/RequirePermission";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toApiError } from "@/lib/api";
import { marketplaceService } from "@/services/marketplace";
import {
  ASTRA_PACKAGE_KINDS,
  isMarketplaceImportResult,
  isMarketplacePreview,
  type MarketplaceExportResponse,
  type MarketplaceImportResult,
  type MarketplacePreview,
} from "@/types";

/**
 * 提取可展示的错误消息。
 *
 * 🔴 `@/lib/api` 拦截器**已**把错误归一化为 `ApiError`（含 `message`）——此处优先读
 *    `message`；仅当收到非归一化错误（无 `message`）时回退 {@link toApiError}。
 */
function resolveErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return toApiError(error).message;
}

/** 读取本地文件为文本（R14：前端只读**文本**，不解析 yaml）。 */
function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error("读取文件失败"));
    reader.readAsText(file);
  });
}

/** 以**文本**下载（R14：导出走文本下载；不解析 yaml）。 */
function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/yaml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * Marketplace（W8 / T2-44；设计 §2.13.1；裁定 R5 / R14）。
 *
 * - **导入**：读取本地包 **yaml 原文**（或直接粘贴）→ **预检**（展示作者 / 版本 / 兼容范围 /
 *   权限声明 / 依赖 / 摘要 + 签名提示）→ **确认导入**；
 * - **导出**：按 `kind` + `id` 取**规范化 yaml 文本**并下载。
 *
 * 🔴 R14：前端**不引入 `js-yaml`**（不解析 yaml）——元数据由**后端**返回；
 *    校验 SHA-256（提供则校验，不匹配拒绝，见后端）；发布 / 安装均不代表信任。
 * 🔴 动作级守卫经 {@link RequirePermission}（`can()`）：导入 `marketplace:import`、
 *    导出 `marketplace:export`。
 */
export function Marketplace() {
  const [packageYaml, setPackageYaml] = useState("");
  const [expectedSha, setExpectedSha] = useState("");
  const [preview, setPreview] = useState<MarketplacePreview | null>(null);
  const [importResult, setImportResult] = useState<MarketplaceImportResult | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const [exportKind, setExportKind] = useState<string>("agent");
  const [exportId, setExportId] = useState("");
  const [exportResult, setExportResult] = useState<MarketplaceExportResponse | null>(null);

  // 导入（同一端点：`confirm=false` 预检 / `confirm=true` 落库）。
  const importMutation = useMutation({ mutationFn: marketplaceService.importPackage });
  const exportMutation = useMutation({ mutationFn: marketplaceService.exportPackage });

  const handleFile = (fileList: FileList | null): void => {
    const file = fileList?.[0];
    if (!file) {
      return;
    }
    readFileAsText(file)
      .then((text) => {
        setPackageYaml(text);
        setPreview(null);
        setImportResult(null);
        setFeedback(`已读取 ${file.name}`);
      })
      .catch((error) => setFeedback(resolveErrorMessage(error)));
  };

  const handlePreview = (): void => {
    if (!packageYaml.trim()) {
      setFeedback("请先读取或粘贴包 yaml 内容");
      return;
    }
    importMutation.mutate(
      {
        package_yaml: packageYaml,
        expected_sha256: expectedSha.trim() || null,
        confirm: false,
      },
      {
        onSuccess: (response) => {
          if (isMarketplacePreview(response)) {
            setPreview(response);
            setImportResult(null);
            setFeedback("预检完成：请核对元数据后确认导入");
          }
        },
        onError: (error) => {
          setPreview(null);
          setFeedback(resolveErrorMessage(error));
        },
      },
    );
  };

  const handleConfirm = (): void => {
    if (!preview) {
      setFeedback("请先预检");
      return;
    }
    importMutation.mutate(
      {
        package_yaml: packageYaml,
        expected_sha256: expectedSha.trim() || null,
        confirm: true,
      },
      {
        onSuccess: (response) => {
          if (isMarketplaceImportResult(response)) {
            setImportResult(response);
            setPreview(null);
            setFeedback(`已导入 ${response.kind}/${response.name}@${response.version}`);
          }
        },
        onError: (error) => setFeedback(resolveErrorMessage(error)),
      },
    );
  };

  const handleExport = (): void => {
    if (!exportId.trim()) {
      setFeedback("请填写资源 id");
      return;
    }
    exportMutation.mutate(
      { kind: exportKind, id: exportId.trim() },
      {
        onSuccess: (response) => {
          setExportResult(response);
          setFeedback("导出完成");
        },
        onError: (error) => setFeedback(resolveErrorMessage(error)),
      },
    );
  };

  const handleDownload = (): void => {
    if (!exportResult) {
      return;
    }
    downloadText(`${exportResult.kind}-${exportResult.id}.yaml`, exportResult.yaml);
  };

  return (
    <div className="space-y-4" data-testid="marketplace">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Marketplace</h1>
        {feedback ? (
          <span className="text-xs text-muted-foreground" data-testid="marketplace-feedback">
            {feedback}
          </span>
        ) : null}
      </div>

      {/* 导入 */}
      <Card>
        <CardHeader>
          <CardTitle>导入包</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground" data-testid="marketplace-r14-note">
            前端仅上传 **yaml 原文**，不解析 YAML（元数据由后端返回）；发布 / 安装均不代表信任。
          </p>
          <div className="space-y-2">
            <Label htmlFor="marketplace-file">本地包文件（`astra-package.yaml`）</Label>
            <Input
              id="marketplace-file"
              data-testid="marketplace-file-input"
              type="file"
              accept=".yaml,.yml,text/yaml"
              onChange={(event) => handleFile(event.target.files)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="marketplace-yaml">包 yaml 原文</Label>
            <textarea
              id="marketplace-yaml"
              data-testid="marketplace-yaml-input"
              className="min-h-[140px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
              value={packageYaml}
              onChange={(event) => setPackageYaml(event.target.value)}
              placeholder="kind: agent&#10;name: my-agent&#10;version: 1.2.0&#10;…"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="marketplace-sha">期望 SHA-256（可选）</Label>
            <Input
              id="marketplace-sha"
              data-testid="marketplace-expected-sha-input"
              value={expectedSha}
              onChange={(event) => setExpectedSha(event.target.value)}
              placeholder="提供则校验，不匹配将拒绝"
            />
          </div>
          <Button
            size="sm"
            data-testid="marketplace-preview-button"
            onClick={handlePreview}
            disabled={importMutation.isPending}
          >
            预检
          </Button>

          {preview ? (
            <div
              className="space-y-2 rounded-md border p-3 text-sm"
              data-testid="marketplace-preview"
            >
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">类型</span>
                <span data-testid="marketplace-preview-kind">{preview.kind}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">名称</span>
                <span data-testid="marketplace-preview-name">{preview.name}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">版本</span>
                <span data-testid="marketplace-preview-version">{preview.version}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">兼容范围</span>
                <span data-testid="marketplace-preview-core-compat">{preview.core_compat}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">作者</span>
                <span data-testid="marketplace-preview-author">{preview.author}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">许可</span>
                <span data-testid="marketplace-preview-license">{preview.license}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">依赖</span>
                <span data-testid="marketplace-preview-dependencies">
                  {preview.dependencies.length > 0 ? preview.dependencies.join(", ") : "无"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">清单路径</span>
                <span className="font-mono text-xs" data-testid="marketplace-preview-manifest-path">
                  {preview.manifest_path}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">摘要</span>
                <span className="font-mono text-xs" data-testid="marketplace-preview-sha">
                  {preview.artifact_sha256}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">签名</span>
                <span data-testid="marketplace-preview-signature">
                  {preview.signature_present ? (
                    <Badge variant="default">已签名</Badge>
                  ) : (
                    <Badge variant="secondary">未签名</Badge>
                  )}
                </span>
              </div>
            </div>
          ) : null}

          <RequirePermission code="marketplace:import">
            <Button
              size="sm"
              data-testid="marketplace-confirm-button"
              onClick={handleConfirm}
              disabled={!preview || importMutation.isPending}
            >
              确认导入
            </Button>
          </RequirePermission>

          {importResult ? (
            <div
              className="rounded-md border border-primary p-3 text-sm"
              data-testid="marketplace-import-result"
            >
              已导入 {importResult.kind}/{importResult.name}@{importResult.version}（摘要{" "}
              <span className="font-mono text-xs">{importResult.digest}</span>）
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* 导出 */}
      <Card>
        <CardHeader>
          <CardTitle>导出包</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="marketplace-export-kind">类型</Label>
              <select
                id="marketplace-export-kind"
                data-testid="marketplace-export-kind-select"
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={exportKind}
                onChange={(event) => setExportKind(event.target.value)}
              >
                {ASTRA_PACKAGE_KINDS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="marketplace-export-id">资源 id</Label>
              <Input
                id="marketplace-export-id"
                data-testid="marketplace-export-id-input"
                value={exportId}
                onChange={(event) => setExportId(event.target.value)}
              />
            </div>
          </div>
          <RequirePermission code="marketplace:export">
            <Button
              size="sm"
              data-testid="marketplace-export-button"
              onClick={handleExport}
              disabled={exportMutation.isPending}
            >
              导出 yaml
            </Button>
          </RequirePermission>

          {exportResult ? (
            <div className="space-y-2">
              <textarea
                readOnly
                data-testid="marketplace-export-yaml"
                className="min-h-[140px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs"
                value={exportResult.yaml}
              />
              <Button
                size="sm"
                variant="outline"
                data-testid="marketplace-download"
                onClick={handleDownload}
              >
                下载 yaml
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
