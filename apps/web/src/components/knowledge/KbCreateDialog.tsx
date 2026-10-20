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
import { useCreateKnowledgeBase } from "@/hooks/useKnowledge";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import type { KnowledgeBaseResponse } from "@/types";

/** {@link KbCreateDialog} 属性。 */
export interface KbCreateDialogProps {
  /** 受控开关。 */
  open: boolean;
  /** 开关回调（关闭时组件内部**不**自动重置——重置发生在成功提交后）。 */
  onOpenChange: (open: boolean) => void;
  /** 创建成功回调（透传新库，供调用方选中新库）。 */
  onCreated?: (base: KnowledgeBaseResponse) => void;
}

/**
 * 新建知识库弹窗（V0.4.6 · D-UI 优化波 · B-16）。
 *
 * 名称（必填，`kb-name-input`）+ 描述（可选 textarea，`kb-desc-input`）+
 * 取消 / 创建（`kb-create-submit`）；提交走 `useCreateKnowledgeBase`
 * （payload `description: null | 值`）；成功 → 关弹窗 + `onCreated(base)`。
 *
 * 校验错误就地显示（`kb-create-error`），不打断输入。
 */
export function KbCreateDialog({ open, onOpenChange, onCreated }: KbCreateDialogProps) {
  const { t } = useTranslation();
  const createKb = useCreateKnowledgeBase();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  /** 提交（名称必填校验 → mutation → 成功关弹窗 / 失败就地报错）。 */
  const handleSubmit = (): void => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError(t("knowledge.create.nameRequired"));
      return;
    }
    setError(null);
    createKb.mutate(
      { name: trimmed, description: description.trim() || null },
      {
        onSuccess: (base) => {
          setName("");
          setDescription("");
          setError(null);
          onOpenChange(false);
          onCreated?.(base);
        },
        onError: (mutationError) => setError(toApiError(mutationError).message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="kb-create-dialog">
        <DialogHeader>
          <DialogTitle>{t("knowledge.create.title")}</DialogTitle>
          <DialogDescription>{t("knowledge.list.emptyDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="kb-name">{t("knowledge.create.name")}</Label>
            <Input
              id="kb-name"
              data-testid="kb-name-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kb-desc">{t("knowledge.create.description")}</Label>
            <textarea
              id="kb-desc"
              data-testid="kb-desc-input"
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          {error ? (
            <p data-testid="kb-create-error" className="text-xs text-destructive">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            data-testid="kb-create-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            data-testid="kb-create-submit"
            onClick={handleSubmit}
            disabled={createKb.isPending}
          >
            {t("knowledge.create.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
