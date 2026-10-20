import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDeleteKnowledgeBase } from "@/hooks/useKnowledge";
import { useTranslation } from "@/i18n";
import type { KnowledgeBaseResponse } from "@/types";

/** {@link KbDeleteDialog} 属性。 */
export interface KbDeleteDialogProps {
  /** 受控开关。 */
  open: boolean;
  /** 开关回调。 */
  onOpenChange: (open: boolean) => void;
  /** 待删除的知识库（标题 / 正文数据源）。 */
  base: KnowledgeBaseResponse;
  /** 该库当前文档数（> 0 时在正文展示后果说明；缺省 / 0 → 省略该句）。 */
  documentCount?: number | null;
  /** 删除成功回调（透传被删的库，供调用方回退选中态 + feedback）。 */
  onDeleted?: (base: KnowledgeBaseResponse) => void;
}

/**
 * 删除知识库确认弹窗（V0.4.6 · B-19a）。
 *
 * 标题「删除知识库」；正文 = 库名 + 后果说明（N 篇文档 + 全部索引数据 +
 * 解除智能体绑定，不可恢复；N = 0 / 缺省时省略文档句）。
 * 取消（`kb-delete-cancel`）/ 删除（`kb-delete-submit`，destructive 变体）；
 * 成功 → 关弹窗 + `onDeleted(base)`。本仓无 AlertDialog 原语 → 复用 Dialog。
 */
export function KbDeleteDialog({
  open,
  onOpenChange,
  base,
  documentCount = null,
  onDeleted,
}: KbDeleteDialogProps) {
  const { t } = useTranslation();
  const deleteKb = useDeleteKnowledgeBase();

  /** 确认删除（无表单校验；成功后关弹窗并上抛）。 */
  const handleDelete = (): void => {
    deleteKb.mutate(base.id, {
      onSuccess: () => {
        onOpenChange(false);
        onDeleted?.(base);
      },
      onError: () => {
        // 删除失败（404 / 网络）保留弹窗；用户可重试或取消。
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="kb-delete-dialog">
        <DialogHeader>
          <DialogTitle>{t("knowledge.delete.title")}</DialogTitle>
          <DialogDescription>
            {t("knowledge.delete.confirm", { name: base.name })}
            {typeof documentCount === "number" && documentCount > 0
              ? " " + t("knowledge.delete.consequence", { count: documentCount })
              : ""}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            data-testid="kb-delete-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="destructive"
            data-testid="kb-delete-submit"
            onClick={handleDelete}
            disabled={deleteKb.isPending}
          >
            {t("knowledge.delete.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
