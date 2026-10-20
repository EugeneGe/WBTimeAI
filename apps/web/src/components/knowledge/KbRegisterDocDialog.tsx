import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateDocument } from "@/hooks/useKnowledge";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";

/** {@link KbRegisterDocDialog} 属性。 */
export interface KbRegisterDocDialogProps {
  /** 受控开关。 */
  open: boolean;
  /** 开关回调。 */
  onOpenChange: (open: boolean) => void;
  /** 目标知识库 id（登记文档归属）。 */
  knowledgeBaseId: string;
  /** 成功 / 失败反馈回调（页面级反馈行透传）。 */
  onFeedback?: (message: string) => void;
}

/**
 * 登记文档弹窗（V0.4.6 · D-UI 优化波 · B-16）。
 *
 * 标题（必填，`doc-title-input`）+ 能力边界说明「2b 仅登记元数据，登记后跟踪索引进度」+
 * 取消 / 登记（`doc-create-submit`）；提交走 `useCreateDocument`；
 * 成功 → 关弹窗 + 页面反馈「文档已登记（PENDING，等待索引）」。
 */
export function KbRegisterDocDialog({
  open,
  onOpenChange,
  knowledgeBaseId,
  onFeedback,
}: KbRegisterDocDialogProps) {
  const { t } = useTranslation();
  const createDoc = useCreateDocument();
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  /** 提交（标题必填校验 → mutation → 成功关弹窗并上抛反馈）。 */
  const handleSubmit = (): void => {
    const trimmed = title.trim();
    if (!trimmed) {
      setError(t("knowledge.docDialog.titleRequired"));
      return;
    }
    setError(null);
    createDoc.mutate(
      { knowledgeBaseId, payload: { title: trimmed, source_type: "text" } },
      {
        onSuccess: () => {
          setTitle("");
          setError(null);
          onOpenChange(false);
          onFeedback?.(t("knowledge.docDialog.success"));
        },
        onError: (mutationError) => {
          setError(toApiError(mutationError).message);
          onFeedback?.(toApiError(mutationError).message);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="doc-register-dialog">
        <DialogHeader>
          <DialogTitle>{t("knowledge.docDialog.title")}</DialogTitle>
          <DialogDescription>{t("knowledge.docDialog.hint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="doc-title">{t("knowledge.docDialog.titleLabel")}</Label>
            <Input
              id="doc-title"
              data-testid="doc-title-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          {error ? (
            <p data-testid="doc-register-error" className="text-xs text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            data-testid="doc-register-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            data-testid="doc-create-submit"
            onClick={handleSubmit}
            disabled={createDoc.isPending}
          >
            {t("knowledge.docDialog.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
