import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { useTranslation } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth, useMe } from "@/hooks/useAuth";
import { usePersonalSettings } from "@/hooks/useSettings";
import { toApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { queryKeys } from "@/lib/query";
import { authService } from "@/services/auth";
import type { UpdateUserRequest } from "@/types";

/**
 * 设置 · 个人分区（V0.4.5 B3 · F-11.5；V0.4.5 B5 · F-26 改版）。
 *
 * - **个人信息卡**：头像 + 用户名/邮箱；**用户名行 hover 显铅笔小按钮**（同 Topbar 编辑范式），
 *   点击 → 就地 Input，Enter/blur 提交 `display_name`，Esc 取消；
 *   （**删除**原「显示名」Input + 「保存」按钮块）；
 * - **用量区**：三格主值 `—` 静态占位 + 「未接入」tag + 「用量统计接入后续」说明；
 * - **退出登录**：用量区下方（ghost/destructive 样式，`useAuth().logout()`）。
 *
 * M07-02 #4（写入口收口）：显示名写入改走 `PUT /users/me`（`authService.updateMe`，
 * 域 A「本人信息」语义）；`PUT /settings/personal`（`useUpdatePersonalSettings`）
 * 仅作后端兼容保留，本组件不再调用。
 *
 * `data-testid`：`settings-profile` / `settings-profile-name` / `settings-profile-name-edit` /
 * `settings-profile-name-input` / `settings-profile-feedback` / `settings-profile-fields` /
 * `settings-profile-field-username|display-name|email|user-id` / `settings-profile-usage` /
 * `settings-profile-logout`。
 */
export function ProfileSection() {
  const { t } = useTranslation();
  const personal = usePersonalSettings();
  const me = useMe();
  const queryClient = useQueryClient();
  const { logout } = useAuth();
  const [feedback, setFeedback] = useState<string | null>(null);

  // M07-02 #4：唯一写入口 = `PUT /users/me`；成功后刷新 `me` 与 `personal` 两份缓存
  // （个人分区读的是 `/settings/personal`，两者同源，需同时失效）。
  const updateMe = useMutation({
    mutationFn: (payload: UpdateUserRequest) => authService.updateMe(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.me });
      void queryClient.invalidateQueries({ queryKey: queryKeys.personal });
    },
  });

  // 就地编辑（F-26：替代原「显示名」Input + 保存按钮）。
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      editInputRef.current?.focus();
      editInputRef.current?.select();
    }
  }, [editing]);

  const source = personal.data?.display_name?.trim() || personal.data?.username?.trim() || "";
  const initial = source ? source.slice(0, 1).toUpperCase() : "观";

  const startEdit = (): void => {
    setDraftName(personal.data?.display_name ?? "");
    setEditing(true);
  };

  const commitEdit = (): void => {
    setEditing(false);
    const next = draftName.trim();
    if (next === (personal.data?.display_name ?? "")) {
      return;
    }
    setFeedback(null);
    updateMe.mutate(
      { display_name: next || null },
      {
        onSuccess: () => setFeedback("saved"),
        onError: (error) => setFeedback(toApiError(error).message),
      },
    );
  };

  const onEditKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitEdit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      setEditing(false);
    }
  };

  return (
    <section
      aria-label={t("settings.profile.title")}
      data-testid="settings-profile"
      className="space-y-6"
    >
      <h3 className="text-sm font-semibold text-foreground">{t("settings.profile.title")}</h3>

      {/* 个人信息卡：头像 + 用户名（hover 显铅笔就地编辑）+ 邮箱。 */}
      <div className="flex items-center gap-3 rounded-lg border border-border px-4 py-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-medium text-primary-foreground">
          {initial}
        </span>
        <span className="flex min-w-0 flex-col">
          {editing ? (
            <Input
              ref={editInputRef}
              data-testid="settings-profile-name-input"
              value={draftName}
              aria-label={t("settings.profile.displayName")}
              placeholder={t("settings.profile.displayName")}
              onChange={(event) => setDraftName(event.target.value)}
              onKeyDown={onEditKeyDown}
              onBlur={commitEdit}
              className="h-6 w-[220px] text-sm"
            />
          ) : (
            <span className="group flex min-w-0 items-center gap-1">
              <span
                data-testid="settings-profile-name"
                className="truncate text-sm font-medium text-foreground"
              >
                {source || "—"}
              </span>
              <button
                type="button"
                data-testid="settings-profile-name-edit"
                aria-label={t("settings.profile.editName")}
                title={t("settings.profile.editName")}
                onClick={startEdit}
                className="flex h-5 w-5 flex-none items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-accent/15 hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </span>
          )}
          <span className="truncate text-xs text-muted-foreground">
            {personal.data?.email ?? ""}
          </span>
        </span>
        {feedback !== null ? (
          feedback === "saved" ? (
            <Check
              data-testid="settings-profile-feedback"
              className="ml-auto h-4 w-4 text-primary"
            />
          ) : (
            <span
              data-testid="settings-profile-feedback"
              className="ml-auto text-xs text-muted-foreground"
            >
              {feedback}
            </span>
          )
        ) : null}
      </div>

      {/* B-17：四格只读信息（数据源 `/users/me`；显示名与身份卡同源口径）。
          用户 ID 用 mono 字体 + 截断（title 悬浮全文）；显示名空 → 「—（点铅笔设置）」。 */}
      <dl className="grid grid-cols-2 gap-2.5 lg:grid-cols-4" data-testid="settings-profile-fields">
        <ProfileField
          testId="settings-profile-field-username"
          label={t("settings.profile.field.username")}
          value={me.data?.username ?? "—"}
        />
        <ProfileField
          testId="settings-profile-field-display-name"
          label={t("settings.profile.field.displayName")}
          value={me.data?.display_name?.trim() || t("settings.profile.field.displayNameEmpty")}
        />
        <ProfileField
          testId="settings-profile-field-email"
          label={t("settings.profile.field.email")}
          value={me.data?.email ?? "—"}
        />
        <ProfileField
          testId="settings-profile-field-user-id"
          label={t("settings.profile.field.userId")}
          value={me.data?.id ?? "—"}
          mono
        />
      </dl>

      {/* 用量区（前端占位；Q5=A：后端无统计端点，展示 `—` + 后续接入说明）。 */}
      <div
        data-testid="settings-profile-usage"
        className="space-y-3 rounded-lg border border-border bg-muted/30 px-4 py-3"
      >
        <p className="text-sm font-medium text-foreground">{t("settings.profile.usage")}</p>
        <dl className="grid grid-cols-3 gap-3">
          <UsageMetric label={t("settings.profile.usage.tokens")} />
          <UsageMetric label={t("settings.profile.usage.peak")} />
          <UsageMetric label={t("settings.profile.usage.streak")} />
        </dl>
        <p className="text-xs text-muted-foreground">{t("settings.profile.usage.note")}</p>
      </div>

      {/* 退出登录（F-26：ghost/destructive 样式，复用 `useAuth().logout()`）。 */}
      <div className="flex justify-start border-t border-border pt-4">
        <Button
          type="button"
          variant="ghost"
          data-testid="settings-profile-logout"
          disabled={logout.isPending}
          onClick={() => logout.mutate()}
          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
        >
          {t("settings.profile.logout")}
        </Button>
      </div>
    </section>
  );
}

/** 四格只读信息 cell（`bg-muted/30` 细边框；用户 ID 走 mono 截断）。 */
function ProfileField({
  label,
  value,
  testId,
  mono = false,
}: {
  label: string;
  value: string;
  testId: string;
  mono?: boolean;
}) {
  return (
    <div data-testid={testId} className="min-w-0 rounded-lg border bg-muted/30 px-2.5 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        title={value}
        className={cn(
          "mt-0.5 truncate text-sm font-medium text-foreground",
          mono && "font-mono text-xs",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/** 用量指标（占位值 `—` + 「未接入」tag；M07-02 #5：`0` 与「未接入」必须视觉可分）。 */
function UsageMetric({ label }: { label: string }) {
  const { t } = useTranslation();
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="flex items-center gap-1.5 text-sm font-medium text-foreground">
        <span>—</span>
        <span className="rounded border border-border px-1 text-[11px] font-normal leading-4 text-muted-foreground">
          {t("settings.profile.usage.notConnected")}
        </span>
      </dd>
    </div>
  );
}
