import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDevices, useMe } from "@/hooks/useAuth";
import { authService } from "@/services/auth";
import { useAuthStore } from "@/stores/authStore";

/** 用户页：本人信息 + 设备会话列表 + 「退出全部」。 */
export function User() {
  const { data: user, isLoading } = useMe();
  const { data: devices } = useDevices();
  const clearSession = useAuthStore((state) => state.clearSession);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const logoutAll = useMutation({
    mutationFn: () => authService.logoutAll(),
    onSettled: () => {
      clearSession();
      queryClient.clear();
      navigate("/login");
    },
  });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>本人信息</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">加载中…</p>
          ) : user ? (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <InfoItem label="用户名" value={user.username} />
              <InfoItem label="邮箱" value={user.email} />
              <InfoItem label="显示名" value={user.display_name ?? "—"} />
              <InfoItem label="用户 ID" value={user.id} />
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">未获取到用户信息</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>设备会话</CardTitle>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => logoutAll.mutate()}
            disabled={logoutAll.isPending}
          >
            退出全部
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>设备</TableHead>
                <TableHead>IP</TableHead>
                <TableHead>创建时间</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(devices ?? []).map((device) => (
                <TableRow key={device.id}>
                  <TableCell>{device.device ?? "—"}</TableCell>
                  <TableCell>{device.ip_address ?? "—"}</TableCell>
                  <TableCell>{device.created_at ?? "—"}</TableCell>
                  <TableCell>{device.revoked_at ? "已撤销" : "活跃"}</TableCell>
                </TableRow>
              ))}
              {(devices ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground">
                    暂无会话
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}
