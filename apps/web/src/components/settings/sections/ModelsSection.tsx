import { ChevronDown, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import {
  AddModelConfigDialog,
  type ModelConfigKind,
} from "@/components/models/AddModelConfigDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCredentials, useProviderModelsMany, useProviders } from "@/hooks/useModels";
import { useTranslation } from "@/i18n";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/stores/authStore";
import type { ModelProviderResponse, ModelResponse } from "@/types";

/** 列表行：模型 + 所属提供方。 */
interface ModelRow {
  provider: ModelProviderResponse;
  model: ModelResponse;
}

/**
 * 判定提供方的模型类型（列表分组依据）。
 *
 * 新数据由添加表单写入 `config.model_kind`；历史数据无该字段时按 provider_type 回退：
 * `openai_compatible` 视为自定义端点，其余内置类型视为常用模型。
 */
function providerKind(provider: ModelProviderResponse): ModelConfigKind {
  const stored = provider.config?.model_kind;
  if (stored === "custom" || stored === "common") {
    return stored;
  }
  return provider.type === "openai_compatible" ? "custom" : "common";
}

/**
 * 设置 · 模型分区（B-07：页内添加 + 按类型分组折叠）。
 *
 * 变更（用户实测裁定，覆盖 D-UI5「只读跳转卡」）：
 * - **不再跳转 `/models`**：右上角「添加模型配置」直接打开
 *   {@link AddModelConfigDialog}（常用模型 / 自定义模型两类）；
 * - **列表在下方就地展示**：按「常用模型 / 自定义模型」分组，组头可折叠；
 * - 概览三格保留（当前默认模型仍无数据源 → `—` + 未接入；供应商数 / 凭证数）。
 *
 * `data-testid`：`settings-models` / `settings-models-add` /
 * `settings-models-group-{common|custom}` / `settings-models-group-{kind}-toggle` /
 * `settings-models-item-<modelId>` / `settings-models-empty` / `settings-models-load-failed` /
 * `settings-models-retry`。
 */
export interface ModelsSectionProps {
  /** 挂载即打开「添加模型配置」弹窗（输入台「配置自定义模型」直达表单用）。 */
  autoOpenAdd?: boolean;
}

export function ModelsSection({ autoOpenAdd = false }: ModelsSectionProps) {
  const { t } = useTranslation();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const providersQuery = useProviders();
  const credentialsQuery = useCredentials();
  const providers = providersQuery.data ?? [];
  const credentials = credentialsQuery.data ?? [];

  const modelQueries = useProviderModelsMany(providers.map((provider) => provider.id));
  const modelsLoading = modelQueries.some((query) => query.isLoading);

  const [addOpen, setAddOpen] = useState(autoOpenAdd);
  // B-08：弹窗打开时 `autoOpenAdd` 才由父级置真（SettingsDialog 的 open 副作用），
  // 需跟随该变化打开表单——不能只依赖 `useState` 初值。
  useEffect(() => {
    if (autoOpenAdd) {
      setAddOpen(true);
    }
  }, [autoOpenAdd]);
  const [openGroups, setOpenGroups] = useState<Record<ModelConfigKind, boolean>>({
    common: true,
    custom: true,
  });
  // B-09：旧 /models 页下线后，凭证掩码列表并入本分区（唯一模型管理面）。
  const [credentialsOpen, setCredentialsOpen] = useState(true);

  const isLoading = providersQuery.isLoading || credentialsQuery.isLoading || modelsLoading;
  const loadFailed = providersQuery.isError || credentialsQuery.isError;
  const hasNoProvider = providers.length === 0;

  const rows: ModelRow[] = providers.flatMap((provider, index) =>
    (modelQueries[index]?.data ?? []).map((model) => ({ provider, model })),
  );

  /** 重试：概览与各 provider 的模型查询都触发。 */
  const handleRetry = (): void => {
    void providersQuery.refetch();
    void credentialsQuery.refetch();
    for (const query of modelQueries) {
      void query.refetch();
    }
  };

  const groups: readonly { kind: ModelConfigKind; labelKey: string }[] = [
    { kind: "common", labelKey: "settings.models.group.common" },
    { kind: "custom", labelKey: "settings.models.group.custom" },
  ];

  return (
    <section
      aria-label={t("settings.models.title")}
      data-testid="settings-models"
      className="space-y-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">{t("settings.models.title")}</h3>
        <Button
          type="button"
          size="sm"
          data-testid="settings-models-add"
          disabled={!isAuthenticated}
          title={isAuthenticated ? undefined : t("settings.models.loginRequired")}
          onClick={() => setAddOpen(true)}
        >
          <Plus className="h-4 w-4" />
          {t("settings.models.add")}
        </Button>
      </div>

      {isLoading ? (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Skeleton className="h-[58px] w-full" />
            <Skeleton className="h-[58px] w-full" />
            <Skeleton className="h-[58px] w-full" />
          </div>
          <Skeleton className="h-24 w-full" />
        </>
      ) : loadFailed ? (
        // 批 F · F2：加载失败 → 不渲染 0/0/0 概览（避免伪装成「尚未配置」），改一行提示 + 重试。
        <div className="flex items-center gap-3">
          <p data-testid="settings-models-load-failed" className="text-sm text-muted-foreground">
            {t("settings.models.jump.loadFailed")}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="settings-models-retry"
            onClick={handleRetry}
          >
            {t("settings.models.jump.retry")}
          </Button>
        </div>
      ) : (
        <>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {/* ① 当前默认模型：前端无数据源 → 占位 `—` + 「未接入」。 */}
            <div
              data-testid="settings-models-default-model"
              className="rounded-lg border border-border px-4 py-2.5"
            >
              <dt className="text-xs text-muted-foreground">
                {t("settings.models.jump.defaultModel")}
              </dt>
              <dd className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                <span>—</span>
                <span className="rounded border border-border px-1 text-[11px] font-normal leading-4 text-muted-foreground">
                  {t("settings.models.jump.notConnected")}
                </span>
              </dd>
            </div>

            {/* ② 已配供应商数量。 */}
            <div
              data-testid="settings-models-provider-count"
              className="rounded-lg border border-border px-4 py-2.5"
            >
              <dt className="text-xs text-muted-foreground">
                {t("settings.models.jump.providers")}
              </dt>
              <dd className="text-sm font-medium text-foreground">{providers.length}</dd>
            </div>

            {/* ③ 凭证数量（仅数量，不展示掩码）。 */}
            <div
              data-testid="settings-models-credential-count"
              className="rounded-lg border border-border px-4 py-2.5"
            >
              <dt className="text-xs text-muted-foreground">
                {t("settings.models.jump.credentials")}
              </dt>
              <dd className="text-sm font-medium text-foreground">{credentials.length}</dd>
            </div>
          </dl>

          {/* 空态：成功且无提供方时引导用右上角按钮添加。 */}
          {hasNoProvider ? (
            <p data-testid="settings-models-empty" className="text-sm text-muted-foreground">
              {t("settings.models.jump.empty")}
            </p>
          ) : null}

          {/* 模型列表：按类型分组，可折叠。 */}
          <div className="space-y-3" data-testid="settings-models-list">
            {groups.map(({ kind, labelKey }) => {
              const items = rows.filter((row) => providerKind(row.provider) === kind);
              const expanded = openGroups[kind];
              return (
                <section key={kind} data-testid={`settings-models-group-${kind}`}>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    data-testid={`settings-models-group-${kind}-toggle`}
                    onClick={() =>
                      setOpenGroups((previous) => ({ ...previous, [kind]: !previous[kind] }))
                    }
                    className="flex w-full items-center gap-2 py-1.5 text-left text-sm font-medium text-foreground"
                  >
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 text-muted-foreground transition-transform",
                        !expanded && "-rotate-90",
                      )}
                    />
                    <span>{t(labelKey)}</span>
                    <span className="rounded-full bg-muted px-1.5 text-[11px] font-normal text-muted-foreground">
                      {items.length}
                    </span>
                  </button>

                  {expanded ? (
                    items.length === 0 ? (
                      <p
                        data-testid={`settings-models-group-${kind}-empty`}
                        className="pl-6 text-xs text-muted-foreground"
                      >
                        {t("settings.models.group.empty")}
                      </p>
                    ) : (
                      <ul className="mt-1 space-y-1.5 pl-6">
                        {items.map(({ provider, model }) => (
                          <li
                            key={model.id}
                            data-testid={`settings-models-item-${model.id}`}
                            className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-foreground">
                                {model.name}
                              </p>
                              <p className="truncate text-xs text-muted-foreground">
                                {provider.name}
                                {model.context_window
                                  ? ` · ${model.context_window.toLocaleString()} ctx`
                                  : ""}
                              </p>
                            </div>
                            <span className="flex-none rounded border border-border px-1.5 text-[11px] uppercase text-muted-foreground">
                              {model.type}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )
                  ) : null}
                </section>
              );
            })}
          </div>

          {/* 凭证（仅掩码）：B-09 自旧 /models 页并入，保留可见性、不展示明文。 */}
          <section data-testid="settings-models-group-credentials">
            <button
              type="button"
              aria-expanded={credentialsOpen}
              data-testid="settings-models-group-credentials-toggle"
              onClick={() => setCredentialsOpen((previous) => !previous)}
              className="flex w-full items-center gap-2 py-1.5 text-left text-sm font-medium text-foreground"
            >
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform",
                  !credentialsOpen && "-rotate-90",
                )}
              />
              <span>{t("settings.models.group.credentials")}</span>
              <span className="rounded-full bg-muted px-1.5 text-[11px] font-normal text-muted-foreground">
                {credentials.length}
              </span>
            </button>

            {credentialsOpen ? (
              credentials.length === 0 ? (
                <p
                  data-testid="settings-models-group-credentials-empty"
                  className="pl-6 text-xs text-muted-foreground"
                >
                  {t("settings.models.group.credentials.empty")}
                </p>
              ) : (
                <ul className="mt-1 space-y-1.5 pl-6">
                  {credentials.map((credential) => (
                    <li
                      key={credential.id}
                      data-testid={`settings-models-credential-${credential.id}`}
                      className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">
                          {credential.provider}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {credential.key_type}
                        </p>
                      </div>
                      <span className="flex-none font-mono text-xs text-muted-foreground">
                        {credential.masked_value}
                      </span>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </section>
        </>
      )}

      <AddModelConfigDialog open={addOpen} onOpenChange={setAddOpen} />
    </section>
  );
}
