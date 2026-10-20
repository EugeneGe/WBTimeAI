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
 * 注册表单校验（消息存 i18n key，渲染时经 `t()` 翻译）。
 * V0.4.5 B4 · F-19.2：「口令」→「密码」。
 */
const registerSchema = z.object({
  username: z.string().min(1, "auth.error.usernameRequired").max(150),
  email: z.string().min(1, "auth.error.emailRequired").email("auth.error.emailInvalid").max(320),
  password: z.string().min(6, "auth.error.passwordMin").max(256),
  display_name: z.string().max(255).optional(),
});

type RegisterForm = z.infer<typeof registerSchema>;

/**
 * 注册页（提交 → `/auth/register`；成功自动登录并进入）。
 *
 * D-UI WS-P2：公开页品牌化——套用 `PageContainer`（默档）+ 品牌标 +
 * token 语义色；校验与提交行为不变。载态 = 提交 pending（按钮文案）。
 *
 * V0.4.5 B4 · F-19.2：「口令」→「密码」；文案统一走 i18n `auth.*`。
 */
export function Register() {
  const { t } = useTranslation();
  const { register: registerUser } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema),
    defaultValues: { username: "", email: "", password: "", display_name: "" },
  });

  const onSubmit = handleSubmit((values) => {
    setError(null);
    registerUser.mutate(
      {
        username: values.username,
        email: values.email,
        password: values.password,
        display_name: values.display_name || null,
      },
      {
        onError: (err) => setError(toApiError(err).message),
      },
    );
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
          <CardTitle>{t("auth.register.title")}</CardTitle>
          <CardDescription>{t("auth.register.subtitle")}</CardDescription>
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
              <Label htmlFor="email">{t("auth.email")}</Label>
              <Input id="email" type="email" autoComplete="email" {...register("email")} />
              {errors.email ? (
                <p className="text-xs text-destructive">{t(errors.email.message ?? "")}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">{t("auth.password")}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                {...register("password")}
              />
              {errors.password ? (
                <p className="text-xs text-destructive">{t(errors.password.message ?? "")}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="display_name">{t("auth.displayNameOptional")}</Label>
              <Input id="display_name" {...register("display_name")} />
            </div>
            {/* 表单级错误（M01-02 #9）：保持单行红字；读屏只用 `role="alert"`
                （隐含 assertive）——**不**叠加 `aria-live="polite"`（语义冲突）。 */}
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
            <Button className="w-full" type="submit" disabled={registerUser.isPending}>
              {registerUser.isPending ? t("auth.register.submitting") : t("auth.register.submit")}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            {t("auth.register.hasAccount")}{" "}
            <Link className="text-primary underline-offset-4 hover:underline" to="/login">
              {t("auth.login.link")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
