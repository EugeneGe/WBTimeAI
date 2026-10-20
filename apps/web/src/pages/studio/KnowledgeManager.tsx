import { BookOpen, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { KbCreateDialog } from "@/components/knowledge/KbCreateDialog";
import { KbDeleteDialog } from "@/components/knowledge/KbDeleteDialog";
import { KbRegisterDocDialog } from "@/components/knowledge/KbRegisterDocDialog";
import { KbRenameDialog } from "@/components/knowledge/KbRenameDialog";
import { KbStatusBadge } from "@/components/knowledge/KbStatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { InlineEmpty } from "@/components/common/InlineEmpty";
import { PageContainer } from "@/components/layout/PageContainer";
import { TabErrorPanel } from "@/components/agents/TabPanels";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDocuments, useKnowledgeBases, useSearchKnowledge } from "@/hooks/useKnowledge";
import { useTranslation } from "@/i18n";
import { formatRelativeTime } from "@/lib/agentDisplay";
import { cn } from "@/lib/cn";
import { toApiError } from "@/lib/api";
import type { KnowledgeBaseResponse, SearchResponse } from "@/types";

/** Document 索引进度映射（`status` → 百分比；供进度条展示）。 */
function statusPercent(status: string): number {
  switch (status) {
    case "PENDING":
      return 10;
    case "PARSING":
      return 35;
    case "CHUNKING":
      return 60;
    case "EMBEDDING":
      return 85;
    case "READY":
    case "FAILED":
      return 100;
    default:
      return 0;
  }
}

/** 30px 图标块（名称首字，雾蓝底；B-16 列表项与概要头共用）。 */
function KbIcon({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-lg bg-primary/10 text-[13px] font-medium text-primary"
    >
      {name.trim().charAt(0) || "—"}
    </span>
  );
}

/**
 * 知识库页（W6 / T2-35；设计 §2.6 / §2.12；V0.4.6 · D-UI 优化波 · B-16）。
 *
 * - H1 走 i18n `knowledge.title`（原硬编码「Knowledge Manager」退场）+ 副标题；
 * - 左栏：知识库列表卡（卡头「＋ 新建」弹窗承载；列表项 = 图标块 + 名称 + meta + 状态徽标）；
 * - 右栏：未选中 → 三步引导空态（唯一 CTA）；选中 → KB 概要头 + 文档卡（登记改弹窗）+ 检索命中卡；
 * - 四态：三份查询 loading → 骨架、isError → 卡内错误面板（复用 B-15 `TabErrorPanel`）；
 * - **所有 EmptyState 显式传 `chips={[]}`**（聊天招呼语 chips 全部退场）；
 * - 能力边界文案如实保留：「2b 仅登记元数据」「语义 / 关键字自动回落」。
 */
export function KnowledgeManager() {
  const { t } = useTranslation();
  const { data: bases, isLoading, isError, error, refetch } = useKnowledgeBases();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  // B-19a：改名 / 删除目标（null = 弹窗关闭）。
  const [renameTarget, setRenameTarget] = useState<KnowledgeBaseResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeBaseResponse | null>(null);

  const effectiveBases = bases ?? [];
  const effectiveId = selectedId ?? effectiveBases[0]?.id ?? null;
  const selectedBase = effectiveBases.find((base) => base.id === effectiveId) ?? null;

  /** 列表项 meta：`description` 优先，否则 `created_at` 相对时间。 */
  const baseMeta = (base: KnowledgeBaseResponse): string =>
    base.description?.trim() || formatRelativeTime(base.created_at, t) || "—";

  return (
    <PageContainer width="wide">
      <div className="space-y-4">
        {/* 页头：H1 + 副标题（feedback 有值才渲染，小字一行）。 */}
        <div className="space-y-1">
          <h1 className="text-title font-medium text-primary">{t("knowledge.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("knowledge.subtitle")}</p>
          {feedback ? (
            <p className="text-xs text-muted-foreground" data-testid="knowledge-feedback">
              {feedback}
            </p>
          ) : null}
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
          {/* 左：知识库列表卡（新建收进卡头按钮 → 弹窗；B-19b：sticky + 内部滚动） */}
          <Card className="flex max-h-[calc(100vh-2rem)] flex-col lg:sticky lg:top-4">
            <CardHeader className="flex flex-none flex-row items-center justify-between space-y-0">
              <CardTitle>{t("knowledge.list.title")}</CardTitle>
              <Button size="sm" data-testid="kb-create-open" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden className="h-3.5 w-3.5" />
                {t("knowledge.list.create")}
              </Button>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 overflow-y-auto">
              {isLoading ? (
                <div className="space-y-2" data-testid="kb-list">
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                </div>
              ) : isError ? (
                <TabErrorPanel
                  testId="kb-error"
                  retryTestId="kb-retry"
                  error={error}
                  onRetry={() => void refetch()}
                />
              ) : effectiveBases.length === 0 ? (
                <div data-testid="kb-list">
                  {/* B-27：空库只在列表卡内给一句「暂无知识库」，不再画右侧三步引导卡；
                      新建入口就是卡头那一个按钮，空态不重复放 CTA。 */}
                  <InlineEmpty
                    icon={BookOpen}
                    title={t("knowledge.list.emptyTitle")}
                    description={t("knowledge.list.emptyDescription")}
                    testId="kb-empty"
                  />
                </div>
              ) : (
                <ul className="space-y-1" data-testid="kb-list">
                  {effectiveBases.map((base) => (
                    <li key={base.id} className="group/kb-item relative">
                      <button
                        type="button"
                        data-testid={`kb-item-${base.name}`}
                        onClick={() => setSelectedId(base.id)}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-lg border p-2.5 text-left transition-colors",
                          effectiveId === base.id
                            ? "border-accent bg-accent/10"
                            : "border-transparent bg-transparent hover:bg-muted/50",
                        )}
                      >
                        <KbIcon name={base.name} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-foreground">
                            {base.name}
                          </span>
                          <span className="block truncate text-[11px] text-muted-foreground">
                            {baseMeta(base)}
                          </span>
                        </span>
                        {/* 徽标：hover / focus-within 时让位给操作组（占位防挤压名称）。 */}
                        <span className="flex-none transition-opacity group-hover/kb-item:opacity-0 group-focus-within/kb-item:opacity-0">
                          <KbStatusBadge status={base.status} />
                        </span>
                      </button>
                      {/* B-19a：改名 / 删除 hover 操作组（覆盖徽标位；键盘可达）。 */}
                      <span className="pointer-events-none absolute right-2.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5 opacity-0 transition-opacity group-hover/kb-item:pointer-events-auto group-hover/kb-item:opacity-100 group-focus-within/kb-item:pointer-events-auto group-focus-within/kb-item:opacity-100">
                        <button
                          type="button"
                          data-testid={`kb-edit-${base.name}`}
                          aria-label={t("knowledge.rename.title")}
                          title={t("knowledge.rename.title")}
                          onClick={(event) => {
                            event.stopPropagation();
                            setRenameTarget(base);
                          }}
                          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent/15 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <Pencil aria-hidden className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          data-testid={`kb-delete-${base.name}`}
                          aria-label={t("knowledge.delete.title")}
                          title={t("knowledge.delete.title")}
                          onClick={(event) => {
                            event.stopPropagation();
                            setDeleteTarget(base);
                          }}
                          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent/15 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <Trash2 aria-hidden className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {/* 右：选中 → KB 工作区；无库 → 留白（B-27 起不再画三步引导卡）。 */}
          <div>
            {isLoading ? (
              <div className="space-y-4">
                <Skeleton className="h-14 w-full rounded-xl" />
                <Skeleton className="h-44 w-full rounded-xl" />
                <Skeleton className="h-56 w-full rounded-xl" />
              </div>
            ) : selectedBase ? (
              <KbWorkspace key={selectedBase.id} base={selectedBase} onFeedback={setFeedback} />
            ) : null}
          </div>
        </div>
      </div>

      {/* 新建知识库弹窗（成功 → 关弹窗 + 选中新库 + 反馈）。 */}
      <KbCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(base) => {
          setSelectedId(base.id);
          setFeedback(t("knowledge.create.success"));
        }}
      />

      {/* 改名弹窗（B-19a：成功 → 关弹窗 + 反馈；列表 / 概要头经 invalidate 刷新）。 */}
      {renameTarget ? (
        <KbRenameDialog
          open
          onOpenChange={(open) => {
            if (!open) {
              setRenameTarget(null);
            }
          }}
          base={renameTarget}
          onUpdated={() => setFeedback(t("knowledge.rename.success"))}
        />
      ) : null}

      {/* 删除确认弹窗（B-19a：成功 → 关弹窗 + 反馈 + 选中态回退）。 */}
      {deleteTarget ? (
        <KbDeleteConfirm
          base={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={(deleted) => {
            setFeedback(t("knowledge.delete.success"));
            if (selectedId === deleted.id) {
              setSelectedId(null);
            }
            setDeleteTarget(null);
          }}
        />
      ) : null}
    </PageContainer>
  );
}

/** {@link KbDeleteConfirm} 属性。 */
interface KbDeleteConfirmProps {
  /** 待删除的知识库。 */
  base: KnowledgeBaseResponse;
  /** 关闭回调。 */
  onClose: () => void;
  /** 删除成功回调。 */
  onDeleted: (base: KnowledgeBaseResponse) => void;
}

/**
 * 删除确认弹窗容器（B-19a）：就近拉取该库文档数（N 篇后果说明；hook 规则
 * 不允许在页面级按 `deleteTarget` 条件调用 → 收进本包装组件）。
 */
function KbDeleteConfirm({ base, onClose, onDeleted }: KbDeleteConfirmProps) {
  const { data: documents } = useDocuments(base.id);
  return (
    <KbDeleteDialog
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
      base={base}
      documentCount={documents?.length ?? null}
      onDeleted={onDeleted}
    />
  );
}

/** {@link KbWorkspace} 属性。 */
interface KbWorkspaceProps {
  /** 选中的知识库（概要头数据源）。 */
  base: KnowledgeBaseResponse;
  /** 页面级反馈回调（登记成功 / 校验 / 检索错误）。 */
  onFeedback: (message: string) => void;
}

/** 单个知识库的工作区（KB 概要头 + 文档进度 + 登记弹窗 + 检索试跑命中卡）。 */
function KbWorkspace({ base, onFeedback }: KbWorkspaceProps) {
  const { t } = useTranslation();
  const [poll, setPoll] = useState(false);
  const {
    data: documents,
    isLoading: docsLoading,
    isError: docsError,
    error: docsErrorDetail,
    refetch: docsRefetch,
  } = useDocuments(base.id, { poll });
  const search = useSearchKnowledge();

  const [registerOpen, setRegisterOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);

  const documentList = documents ?? [];

  /** 检索（检索词必填；错误走 feedback 文本——既有机制）。 */
  const handleSearch = (): void => {
    if (!query.trim()) {
      onFeedback(t("knowledge.search.queryRequired"));
      return;
    }
    search.mutate(
      { query: query.trim(), knowledge_base_id: base.id, top_k: 5 },
      {
        onSuccess: (response) => setResult(response),
        onError: (error) => onFeedback(toApiError(error).message),
      },
    );
  };

  return (
    <div className="space-y-4">
      {/* KB 概要头：图标块 + 名称 + meta（描述优先，否则相对时间）+ 状态徽标。 */}
      <div className="flex items-center gap-2.5 rounded-xl border bg-card px-3.5 py-2.5">
        <KbIcon name={base.name} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-foreground">{base.name}</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {base.description?.trim() || formatRelativeTime(base.created_at, t) || "—"}
          </div>
        </div>
        <KbStatusBadge status={base.status} />
      </div>

      {/* 文档卡：表头 = 标题 + 自动刷新 toggle + 登记文档（弹窗承载）。 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>{t("knowledge.docs.title")}</CardTitle>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                data-testid="doc-poll-toggle"
                checked={poll}
                onChange={(event) => setPoll(event.target.checked)}
              />
              {t("knowledge.docs.autoRefresh")}
            </label>
            <Button size="sm" data-testid="doc-register-open" onClick={() => setRegisterOpen(true)}>
              <Plus aria-hidden className="h-3.5 w-3.5" />
              {t("knowledge.docs.register")}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {docsLoading ? (
            <div className="space-y-2" data-testid="docs-skeleton">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ) : docsError ? (
            <TabErrorPanel
              testId="docs-error"
              retryTestId="docs-retry"
              error={docsErrorDetail}
              onRetry={() => void docsRefetch()}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("knowledge.docs.colTitle")}</TableHead>
                  <TableHead>{t("knowledge.docs.colSource")}</TableHead>
                  <TableHead>{t("knowledge.docs.colStatus")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documentList.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3}>
                      <EmptyState
                        title={t("knowledge.docs.emptyTitle")}
                        description={t("knowledge.docs.emptyDescription")}
                        chips={[]}
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  documentList.map((document) => (
                    <TableRow key={document.id} data-testid={`doc-row-${document.title}`}>
                      <TableCell className="font-medium">{document.title}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {document.source_type}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span
                            data-testid={`doc-status-${document.title}`}
                            className={cn(
                              "flex-none whitespace-nowrap rounded-full border px-1.5 py-px text-[10px] font-medium leading-4",
                              document.status === "READY"
                                ? "border-[#C9DFD2] bg-[#F0F7F3] text-[#4A7C63]"
                                : document.status === "FAILED"
                                  ? "border-[#EBCBD1] bg-[#FBF1F2] text-[#A84452]"
                                  : "border-[#EBD9AC] bg-[#FDF6E6] text-[#8A6322]",
                            )}
                          >
                            {document.status}
                          </span>
                          <div className="h-1.5 w-24 overflow-hidden rounded bg-muted">
                            <div
                              className={
                                "h-full " +
                                (document.status === "FAILED" ? "bg-destructive" : "bg-primary")
                              }
                              style={{ width: `${statusPercent(document.status)}%` }}
                              data-testid={`doc-progress-${document.title}`}
                            />
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 检索卡：卡头 = 标题 + mode 徽标（仅非语义路且有结果时）；命中升级为命中卡。 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>{t("knowledge.search.title")}</CardTitle>
          {result && result.mode !== "semantic" ? (
            <span
              data-testid="search-mode-badge"
              title={t("knowledge.search.keywordHint")}
              className="flex-none whitespace-nowrap rounded-full border border-[#EBD9AC] bg-[#FDF6E6] px-1.5 py-px text-[10px] font-medium leading-4 text-[#8A6322]"
            >
              {t("knowledge.search.modeKeyword")}
            </span>
          ) : null}
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              data-testid="search-query-input"
              placeholder={t("knowledge.search.placeholder")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button
              size="sm"
              data-testid="search-submit"
              onClick={handleSearch}
              disabled={search.isPending}
            >
              {t("knowledge.search.submit")}
            </Button>
          </div>

          {result ? (
            <div className="space-y-2" data-testid="search-result">
              {result.hits.length === 0 ? (
                <EmptyState
                  title={t("knowledge.search.noHitsTitle")}
                  description={t("knowledge.search.noHitsDescription")}
                  chips={[]}
                />
              ) : (
                <ul className="space-y-2">
                  {result.hits.map((hit) => (
                    <li
                      key={hit.chunk_id}
                      className="rounded-xl border bg-card p-3"
                      data-testid={`search-hit-${hit.chunk_id}`}
                    >
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <span
                          data-testid={`search-hit-score-${hit.chunk_id}`}
                          className="font-semibold text-foreground"
                        >
                          {t("knowledge.search.score", { value: hit.score.toFixed(3) })}
                        </span>
                        <span aria-hidden>·</span>
                        <span
                          data-testid={`search-hit-source-${hit.chunk_id}`}
                          className="min-w-0 truncate"
                        >
                          {t("knowledge.search.cite", { source: hit.source })}
                        </span>
                        <span className="ml-auto flex-none font-mono text-[10px] text-muted-foreground">
                          {hit.chunk_id}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-sm text-foreground">{hit.content}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* 登记文档弹窗（能力边界说明内嵌；成功反馈上抛页面级 feedback 行）。 */}
      <KbRegisterDocDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        knowledgeBaseId={base.id}
        onFeedback={onFeedback}
      />
    </div>
  );
}
