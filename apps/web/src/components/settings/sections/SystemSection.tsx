import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/i18n";
import { useOrganization, useOrganizations, useSystemSettings } from "@/hooks/useSettings";
import { SANDBOX_STRENGTH_NOTE } from "@/lib/chat";

import { AuditSection } from "../AuditSection";
import { PluginSection } from "../PluginSection";

/**
 * 设置 · 系统分区（V0.4.5 B3 · F-11；V0.4.5 B5 · F-26 **移除端口块**；
 * V0.4.6 收口 · **追加插件 / 审计两区块**；V0.4.6 缺陷 L-3 · **追加组织只读卡**）。
 *
 * - 运行模式 / 应用名 / 版本（只读，复用 `useSystemSettings`）；
 * - ~~后端端口~~（F-18.3）：**B5 移除**（端口管理收敛至桌面壳侧）；
 * - **合规明示**：`SANDBOX_STRENGTH_NOTE`（`lib/chat`，冻结常量 C3）继续展示；
 * - **组织**（V0.4.6 缺陷 L-3）：`GET /organizations` + `GET /organizations/{id}`
 *   的**唯一页面入口**——只读展示首条组织的 name / slug / id；
 * - **插件**（V0.4.6 收口 · M07-01 第 12 条）：`GET/POST/DELETE /plugins` 全量落表；
 * - **审计**（同上）：`GET /audit` 只读流水。
 *
 * 🔴 各区块**追加在系统分区内部**，**不新增导航项**（保持 8 分区冻结）；
 *    均**不阻塞核心启动**（各自独立三态，失败仅区块内降级）。
 *
 * `data-testid`：`settings-system-info` / `settings-system-loading` / `settings-sandbox-note` /
 * `settings-organization` / `-loading` / `-error` / `-empty` / `-info` / `-name` / `-slug` / `-id`。
 */
export function SystemSection() {
  const { t } = useTranslation();
  const system = useSystemSettings();

  return (
    <section
      aria-label={t("settings.system.title")}
      data-testid="settings-system"
      className="space-y-5"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.system.title")}</h3>

      {system.data ? (
        <dl data-testid="settings-system-info" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <InfoItem label={t("settings.system.runtimeMode")} value={system.data.mode} />
          <InfoItem label={t("settings.system.appName")} value={system.data.app_name} />
          <InfoItem label={t("settings.system.version")} value={system.data.app_version} />
        </dl>
      ) : (
        <div
          data-testid="settings-system-loading"
          className="grid grid-cols-1 gap-3 sm:grid-cols-3"
        >
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {/* 合规明示（A-1）：`SANDBOX_STRENGTH_NOTE` 自 Chat 顶部 banner 迁移至此。 */}
      <div className="rounded-lg border border-border bg-muted/40 px-4 py-3">
        <p data-testid="settings-sandbox-note" className="text-sm text-foreground">
          {SANDBOX_STRENGTH_NOTE}
        </p>
      </div>

      {/* V0.4.6 缺陷 L-3：组织只读卡（`GET /organizations` + `GET /organizations/{id}`）。 */}
      <OrganizationCard />

      {/* V0.4.6 收口：系统分区内追加「插件」「审计」两区块（不新增导航项）。 */}
      <PluginSection />
      <AuditSection />
    </section>
  );
}

/**
 * 「组织」只读卡（V0.4.6 缺陷 L-3）。
 *
 * 消费链路：`GET /organizations` 取**首条**组织 → 再用其 `id` 调
 * `GET /organizations/{id}` 展示详情（两个接口此前**全仓无组件消费**）。
 *
 * 三态（**互斥**，且都在本卡内降级，不影响其余区块）：
 * - loading：`Skeleton`；
 * - error：muted 文案「加载失败」；
 * - empty：muted 文案「暂无组织」。
 *
 * 🔴 **只读**：不做编辑 / 删除，不引入写请求。
 */
function OrganizationCard() {
  const { t } = useTranslation();
  const organizations = useOrganizations();
  const items = organizations.data ?? [];
  // 首条组织标识（列表未就绪时为空串 → 详情查询 `enabled: false`，不发请求）。
  const firstId = items.length > 0 && items[0] !== undefined ? items[0].id : "";
  const detail = useOrganization(firstId);

  return (
    <section
      aria-label={t("settings.organization.title")}
      data-testid="settings-organization"
      className="space-y-2 border-t border-border pt-5"
    >
      <h4 className="text-sm font-semibold text-foreground">{t("settings.organization.title")}</h4>

      {organizations.isPending ? (
        <div
          data-testid="settings-organization-loading"
          className="grid grid-cols-1 gap-3 sm:grid-cols-3"
        >
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : organizations.isError || detail.isError ? (
        <p data-testid="settings-organization-error" className="text-xs text-muted-foreground">
          {t("settings.organization.loadFailed")}
        </p>
      ) : items.length === 0 ? (
        <p data-testid="settings-organization-empty" className="text-xs text-muted-foreground">
          {t("settings.organization.empty")}
        </p>
      ) : detail.isPending || detail.data === undefined ? (
        <div
          data-testid="settings-organization-loading"
          className="grid grid-cols-1 gap-3 sm:grid-cols-3"
        >
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : (
        <dl
          data-testid="settings-organization-info"
          className="grid grid-cols-1 gap-3 sm:grid-cols-3"
        >
          <div>
            <dt className="text-xs text-muted-foreground">{t("settings.organization.name")}</dt>
            <dd
              data-testid="settings-organization-name"
              className="text-sm font-medium text-foreground"
            >
              {detail.data.name}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{t("settings.organization.slug")}</dt>
            <dd
              data-testid="settings-organization-slug"
              className="text-sm font-medium text-foreground"
            >
              {detail.data.slug}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">{t("settings.organization.id")}</dt>
            <dd
              data-testid="settings-organization-id"
              className="break-all font-mono text-xs text-muted-foreground"
            >
              {detail.data.id}
            </dd>
          </div>
        </dl>
      )}
    </section>
  );
}

/** 系统信息条目。 */
function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium text-foreground">{value}</dd>
    </div>
  );
}
