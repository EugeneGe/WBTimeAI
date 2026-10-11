import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { toApiError } from "@/lib/api";

const registerSchema = z.object({
  username: z.string().min(1, "请输入用户名").max(150),
  email: z.string().email("请输入合法邮箱").max(320),
  password: z.string().min(6, "口令至少 6 位").max(256),
  display_name: z.string().max(255).optional(),
});

type RegisterForm = z.infer<typeof registerSchema>;

/** 注册页（提交 → `/auth/register`；成功自动登录并进入）。 */
export function Register() {
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
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>注册 Astra AI</CardTitle>
          <CardDescription>创建账号后自动登录</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="username">用户名</Label>
              <Input id="username" autoComplete="username" {...register("username")} />
              {errors.username ? (
                <p className="text-xs text-destructive">{errors.username.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="email">邮箱</Label>
              <Input id="email" type="email" autoComplete="email" {...register("email")} />
              {errors.email ? (
                <p className="text-xs text-destructive">{errors.email.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">口令</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                {...register("password")}
              />
              {errors.password ? (
                <p className="text-xs text-destructive">{errors.password.message}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="display_name">显示名（可选）</Label>
              <Input id="display_name" {...register("display_name")} />
            </div>
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <Button className="w-full" type="submit" disabled={registerUser.isPending}>
              {registerUser.isPending ? "注册中…" : "注册"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            已有账号？{" "}
            <Link className="text-primary underline-offset-4 hover:underline" to="/login">
              登录
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
