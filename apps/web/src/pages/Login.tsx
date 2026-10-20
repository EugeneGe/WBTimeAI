import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { DocumentTitle } from "@/components/common/DocumentTitle";
import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { useTranslation } from "@/i18n";
import { toApiError } from "@/lib/api";

/**
 * 登录表单校验（消息存 i18n key，渲染时经 `t()` 翻译）。
 * V0.4.5 B4 · F-19.2：「口令」→「密码」。
 */
const loginSchema = z.object({
  username: z.string().min(1, "auth.error.usernameRequired"),
  password: z.string().min(1, "auth.error.passwordRequired"),
});

type LoginForm = z.infer<typeof loginSchema>;

/**
 * 登录页（RHF + zod → `/auth/login`；423 → 「账号已锁定」提示）。
 *
 * D-UI WS-P2：公开页品牌化首因——套用 `PageContainer`（默档）+ 品牌标 +
 * token 语义色；表单校验与错误分支行为不变。载态 = 提交 pending（按钮文案）。
 *
 * V0.4.5 B4 · F-19.2：
 * - **移除**「初始管理员」凭据提示段（`login-default-admin-hint`，Q4=c：UI 不再提示任何凭据）；
 * - 「口令」→「密码」（label + zod 文案 + 副标题「使用用户名与密码登录」）；
 * - 文案统一走 i18n `auth.*`（标题 / 链路不变）。
 */
export function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
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
      onError: (err) => {
        const apiError = toApiError(err);
        setError(apiError.status === 423 ? t("auth.login.locked") : apiError.message);
      },
    });
  });

  return (
    <PageContainer className="flex min-h-screen items-center justify-center bg-page">
      {/* B-01：公开页不经 `App` 外壳，故在此单独同步 `document.title`（随语言）。 */}
      <DocumentTitle />
      <Card className="w-full max-w-sm">
        <CardHeader className="items-center text-center">
          {/* 品牌标：墨蓝方块 + 三序金点（设计 §06 / §04）。 */}
          <div
            aria-hidden
            data-testid="auth-brand-mark"
            className="mb-2 flex h-11 w-11 items-center justify-center gap-[3px] rounded-xl bg-primary"
          >
            <i className="h-1 w-1 rounded-full bg-accent" />
            <i className="h-1 w-1 rounded-full bg-accent" />
            <i className="h-1 w-1 rounded-full bg-accent" />
          </div>
          <CardTitle>{t("auth.login.title")}</CardTitle>
          <CardDescription>{t("auth.login.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="username">{t("auth.username")}</Label>
              <Input id="username" autoComplete="username" {...register("username")} />
              {errors.username ? (
                <p className="text-xs text-destructive">{t(errors.username.message ?? "")}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">{t("auth.password")}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...register("password")}
              />
              {errors.password ? (
                <p className="text-xs text-destructive">{t(errors.password.message ?? "")}</p>
              ) : null}
            </div>
            {/* 表单级错误（M01-01 #8）：保持单行红字，不引入 ErrorBox 底色块；
                读屏只用 `role="alert"`（隐含 assertive）——**不**再叠加 `aria-live="polite"`，
                两者语义冲突会让播报时机不确定。 */}
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
            <Button className="w-full" type="submit" disabled={login.isPending}>
              {login.isPending ? t("auth.login.submitting") : t("auth.login.submit")}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            {t("auth.login.noAccount")}{" "}
            <Link className="text-primary underline-offset-4 hover:underline" to="/register">
              {t("auth.register.link")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
