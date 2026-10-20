// ---------------------------------------------------------------------------
// WBTimeAI · remoteTaskService 单测（R5Q-03 · 补全轮）
//
// 补覆盖此前**无自动化证据**的远程服务方法（T2-63 §3 #41 前端 Web 取消 / Project Clone 等）：
//   cancel / cloneProject / projectStatus / listGitRefs / downloadArtifact。
// 以 msw 打桩冻结 DTO（snake_case + 统一响应壳）；断言请求命中的**方法 + 路径**与返回 DTO。
// ---------------------------------------------------------------------------
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { remoteTaskService } from "@/services/remoteTask";
import { useAuthStore } from "@/stores/authStore";
import { shell } from "@/test/msw-handlers";
import { server } from "@/test/setup";

interface Seen {
  method: string;
  path: string;
  search: string;
}
const seen: Seen[] = [];

/** 记录一次请求（方法 + 路径 + 查询串）。 */
function record(request: Request): Seen {
  const url = new URL(request.url);
  const entry: Seen = { method: request.method, path: url.pathname, search: url.search };
  seen.push(entry);
  return entry;
}

describe("remoteTaskService（补覆盖 cancel / clone / status / gitRefs / artifact）", () => {
  beforeEach(() => {
    seen.length = 0;
    useAuthStore.setState({ isAuthenticated: true, accessToken: "test", permissions: ["*"] });
  });

  it("cancel 命中 POST /tasks/{id}/cancel（终态）", async () => {
    server.use(
      http.post("/api/v1/tasks/:taskId/cancel", ({ request }) => {
        record(request);
        return shell({ task_id: "t1", status: "CANCELLED" });
      }),
    );

    const result = await remoteTaskService.cancel("t1");

    expect(result.status).toBe("CANCELLED");
    expect(seen[0]).toMatchObject({ method: "POST", path: "/api/v1/tasks/t1/cancel" });
  });

  it("cloneProject 命中 POST /projects/{id}/clone 并返回 {task_id}（202）", async () => {
    server.use(
      http.post("/api/v1/projects/:projectId/clone", ({ request }) => {
        record(request);
        return shell({ task_id: "clone-task-1" }, 202);
      }),
    );

    const result = await remoteTaskService.cloneProject("p1", { base_ref: "main" });

    expect(result.task_id).toBe("clone-task-1");
    expect(seen[0]).toMatchObject({ method: "POST", path: "/api/v1/projects/p1/clone" });
  });

  it("projectStatus 命中 GET /projects/{id}/status 且**不含**宿主路径", async () => {
    server.use(
      http.get("/api/v1/projects/:projectId/status", ({ request }) => {
        record(request);
        return shell({ project_id: "p1", repo_configured: true });
      }),
    );

    const result = await remoteTaskService.projectStatus("p1");

    expect(result.repo_configured).toBe(true);
    expect(JSON.stringify(result)).not.toContain("/"); // 不含宿主路径分隔符
    expect(seen[0]).toMatchObject({ method: "GET", path: "/api/v1/projects/p1/status" });
  });

  it("listGitRefs 命中 GET /projects/{id}/git/refs", async () => {
    server.use(
      http.get("/api/v1/projects/:projectId/git/refs", ({ request }) => {
        record(request);
        return shell([{ name: "refs/heads/main", commit: "a".repeat(40) }]);
      }),
    );

    const refs = await remoteTaskService.listGitRefs("p1");

    expect(refs).toHaveLength(1);
    expect(seen[0]).toMatchObject({ method: "GET", path: "/api/v1/projects/p1/git/refs" });
  });

  it("downloadArtifact 命中 GET /tasks/{id}/artifacts/{name} 并返回 Blob", async () => {
    server.use(
      http.get("/api/v1/tasks/:taskId/artifacts/:name", ({ request }) => {
        record(request);
        return new HttpResponse(new Blob(["artifact-bytes"], { type: "text/plain" }), {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        });
      }),
    );

    const blob = await remoteTaskService.downloadArtifact("t1", "report.txt", { attempt: 1 });

    // jsdom 的 Blob 无 ``.text()``（实现差异）→ 以 size 断言内容非空。
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBeGreaterThan(0);
    expect(seen[0]).toMatchObject({
      method: "GET",
      path: "/api/v1/tasks/t1/artifacts/report.txt",
    });
  });

  it("downloadArtifact 对产物名做 encodeURIComponent（含 / 与 # 时不改变路径结构）", async () => {
    server.use(
      http.get("/api/v1/tasks/:taskId/artifacts/:name", ({ request }) => {
        record(request);
        return new HttpResponse(new Blob(["x"], { type: "text/plain" }), {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        });
      }),
    );

    await remoteTaskService.downloadArtifact("t1", "logs/a#b.txt", { attempt: 2 });

    expect(seen[0]?.method).toBe("GET");
    // `/` → `%2F`、`#` → `%23`：既不会被当成新路径段，也不会被当作片段起点截断。
    expect(seen[0]?.path).toBe("/api/v1/tasks/t1/artifacts/logs%2Fa%23b.txt");
    expect(seen[0]?.path).not.toContain("/artifacts/logs/");
    expect(seen[0]?.search).toBe("?attempt=2");
  });
});
