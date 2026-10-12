// ---------------------------------------------------------------------------
// Astra AI · useRemoteTasks hooks 单测（R5Q-03 · 补全轮）
//
// 补覆盖此前**无自动化证据**的远程 hooks（T2-63 §3 #41 前端 Web 取消 / Project Clone 等）：
//   useProjectStatus / useProjectGitRefs（query）· useCloneProject / useCancelRemoteTask（mutation）。
// 以 msw 打桩冻结 DTO；断言查询成功与请求命中的**方法 + 路径**。
// ---------------------------------------------------------------------------
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  useCancelRemoteTask,
  useCloneProject,
  useProjectGitRefs,
  useProjectStatus,
} from "@/hooks/useRemoteTasks";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

/** 独立 QueryClient（禁用重试），包住被测 hook。 */
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRemoteTasks hooks（补覆盖）", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("useProjectStatus 命中 GET /projects/{id}/status", async () => {
    server.use(
      http.get("/api/v1/projects/:projectId/status", () =>
        shell({ project_id: "p1", repo_configured: true }),
      ),
    );

    const { result } = renderHook(() => useProjectStatus("p1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.repo_configured).toBe(true);
  });

  it("useProjectGitRefs 命中 GET /projects/{id}/git/refs", async () => {
    server.use(
      http.get("/api/v1/projects/:projectId/git/refs", () =>
        shell([{ name: "refs/heads/main" }]),
      ),
    );

    const { result } = renderHook(() => useProjectGitRefs("p1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });

  it("useCloneProject 经 mutation 命中 POST /projects/{id}/clone（202）", async () => {
    let path = "";
    server.use(
      http.post("/api/v1/projects/:projectId/clone", ({ request }) => {
        path = new URL(request.url).pathname;
        return shell({ task_id: "clone-1" }, 202);
      }),
    );

    const { result } = renderHook(() => useCloneProject("p1"), { wrapper });
    const response = await result.current.mutateAsync({ base_ref: "main" });

    expect(response.task_id).toBe("clone-1");
    expect(path).toBe("/api/v1/projects/p1/clone");
  });

  it("useCancelRemoteTask 经 mutation 命中 POST /tasks/{id}/cancel", async () => {
    let path = "";
    server.use(
      http.post("/api/v1/tasks/:taskId/cancel", ({ request }) => {
        path = new URL(request.url).pathname;
        return shell({ task_id: "t1", status: "CANCELLED" });
      }),
    );

    const { result } = renderHook(() => useCancelRemoteTask("t1"), { wrapper });
    const response = await result.current.mutateAsync();

    expect(response.status).toBe("CANCELLED");
    expect(path).toBe("/api/v1/tasks/t1/cancel");
  });
});
