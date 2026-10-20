import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";
import { useAuthGateStore } from "@/stores/authGateStore";

/**
 * 登录表单校验（与 `pages/Login.tsx` **同口径**）。
 *
 * 校验消息存 **i18n key**，渲染时经 `t()` 翻译（避免模块级常量依赖运行时语言）。
 */
const loginSchema = z.object({
  username: z.string().min(1, "auth.error.usernameRequired"),
  password: z.string().min(1, "auth.error.passwordRequired"),
});

type LoginForm = z.infer<typeof loginSchema>;

/**
 * 登录弹窗（V0.4.5 B4 · F-19.2 / F-19.3）。
 *
 * - radix `ui/dialog` 体系（Esc / 点击外部 / 焦点陷阱由原语内建）；
 * - 表单口径与 `Login.tsx` 一致（RHF + zod → `useAuth().login`）；
 * - 开合由 `authGateStore.open` 驱动：匿名用户点头像、或受限操作触发 `requireAuth`；
 * - **登录成功** → `runPending()`（执行此前登记的待办，如「发送消息」）+ 关闭弹窗；
 * - 423 → 「账号已锁定」提示（走 `auth.login.locked`）。
 *
 * `data-testid`：`login-dialog`（内容根）/ `login-dialog-username` / `login-dialog-password` /
 * `login-dialog-submit`。
 */
export function LoginDialog() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const open = useAuthGateStore((state) => state.open);
  const closeLogin = useAuthGateStore((state) => state.closeLogin);
  const runPending = useAuthGateStore((state) => state.runPending);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  const onSubmit = handleSubmit((values) => {
    setError(null);
    login.mutate(values, {
      onSuccess: () => {
        // 先执行登记的待办（如发送消息），再关闭弹窗（closeLogin 兜底清空 pending）。
        runPending();
        closeLogin();
      },
      onError: (err) => {
        const apiError = toApiError(err);
        setError(apiError.status === 423 ? t("auth.login.locked") : apiError.message);
      },
    });
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setError(null);
          closeLogin();
        }
      }}
    >
      <DialogContent data-testid="login-dialog" className="max-w-sm">
        <DialogHeader className="items-center text-center">
          {/* 品牌标：墨蓝方块 + 三序金点（设计 §06 / §04）。 */}
          <div
            aria-hidden
            data-testid="auth-brand-mark"
            className="mx-auto mb-2 flex h-11 w-11 items-center justify-center gap-[3px] rounded-xl bg-primary"
          >
            <i className="h-1 w-1 rounded-full bg-accent" />
            <i className="h-1 w-1 rounded-full bg-accent" />
            <i className="h-1 w-1 rounded-full bg-accent" />
          </div>
          <DialogTitle>{t("auth.login.title")}</DialogTitle>
          <DialogDescription>{t("auth.login.subtitle")}</DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={onSubmit} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="login-dialog-username">{t("auth.username")}</Label>
            <Input
              id="login-dialog-username"
              data-testid="login-dialog-username"
              autoComplete="username"
              {...register("username")}
            />
            {errors.username ? (
              <p className="text-xs text-destructive">{t(errors.username.message ?? "")}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="login-dialog-password">{t("auth.password")}</Label>
            <Input
              id="login-dialog-password"
              data-testid="login-dialog-password"
              type="password"
              autoComplete="current-password"
              {...register("password")}
            />
            {errors.password ? (
              <p className="text-xs text-destructive">{t(errors.password.message ?? "")}</p>
            ) : null}
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button
            className="w-full"
            type="submit"
            data-testid="login-dialog-submit"
            disabled={login.isPending}
          >
            {login.isPending ? t("auth.login.submitting") : t("auth.login.submit")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
