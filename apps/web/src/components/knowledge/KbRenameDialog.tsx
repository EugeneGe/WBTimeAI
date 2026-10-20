import { useEffect, useState } from "react";

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
import { useUpdateKnowledgeBase } from "@/hooks/useKnowledge";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import type { KnowledgeBaseResponse } from "@/types";

/** {@link KbRenameDialog} 属性。 */
export interface KbRenameDialogProps {
  /** 受控开关。 */
  open: boolean;
  /** 开关回调。 */
  onOpenChange: (open: boolean) => void;
  /** 待改名的知识库（名称 / 描述预填数据源）。 */
  base: KnowledgeBaseResponse;
  /** 改名成功回调（透传更新后的库，供调用方反馈 / 刷新选中态）。 */
  onUpdated?: (base: KnowledgeBaseResponse) => void;
}

/**
 * 改名知识库弹窗（V0.4.6 · B-19a）。
 *
 * 名称（预填，`kb-rename-name`）+ 描述（预填，`kb-rename-desc`）+
 * 取消 / 保存（`kb-rename-submit`）；提交走 `useUpdateKnowledgeBase`（PATCH）。
 * 校验错误与 409 同名冲突就地显示（`kb-rename-error`），**不关弹窗**；
 * 成功 → 关弹窗 + `onUpdated(base)`（feedback + invalidate 由调用方 / hook 承担）。
 */
export function KbRenameDialog({ open, onOpenChange, base, onUpdated }: KbRenameDialogProps) {
  const { t } = useTranslation();
  const updateKb = useUpdateKnowledgeBase();
  const [name, setName] = useState(base.name);
  const [description, setDescription] = useState(base.description ?? "");
  const [error, setError] = useState<string | null>(null);

  // 每次打开时以当前库回填（切库 / 列表刷新后不残留上一次草稿）。
  useEffect(() => {
    if (open) {
      setName(base.name);
      setDescription(base.description ?? "");
      setError(null);
    }
  }, [open, base]);

  /** 提交（名称必填校验 → PATCH → 成功关弹窗 / 失败就地报错）。 */
  const handleSubmit = (): void => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("knowledge.rename.nameRequired"));
      return;
    }
    setError(null);
    updateKb.mutate(
      {
        knowledgeBaseId: base.id,
        payload: { name: trimmed, description: description.trim() || null },
      },
      {
        onSuccess: (updated) => {
          setError(null);
          onOpenChange(false);
          onUpdated?.(updated);
        },
        onError: (mutationError) => {
          const apiError = toApiError(mutationError);
          // 409 同名冲突 → 固定行内文案（不关弹窗）；其余展示服务端原文。
          setError(apiError.status === 409 ? t("knowledge.rename.conflict") : apiError.message);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="kb-rename-dialog">
        <DialogHeader>
          <DialogTitle>{t("knowledge.rename.title")}</DialogTitle>
          <DialogDescription>{t("knowledge.rename.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="kb-rename-name-field">{t("knowledge.create.name")}</Label>
            <Input
              id="kb-rename-name-field"
              data-testid="kb-rename-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kb-rename-desc-field">{t("knowledge.create.description")}</Label>
            <textarea
              id="kb-rename-desc-field"
              data-testid="kb-rename-desc"
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          {error ? (
            <p data-testid="kb-rename-error" className="text-xs text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            data-testid="kb-rename-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            data-testid="kb-rename-submit"
            onClick={handleSubmit}
            disabled={updateKb.isPending}
          >
            {t("knowledge.rename.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
