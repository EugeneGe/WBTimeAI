// T1-02 · @wbtime/config：档位、默认值、缺关键配置抛明确错误类型。

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ConfigError,
  ENV_KEYS,
  loadConfig,
  tryLoadConfig,
} from "../dist/index.js";

test("local 档：默认档位 + SQLite 兜底路径", () => {
  const cfg = loadConfig({});
  assert.equal(cfg.mode, "local");
  assert.equal(cfg.databaseUrl, "sqlite:./.wbtime/wbtime.db");
  assert.equal(cfg.port, 8000);
  assert.equal(cfg.logLevel, "info");
});

test("server 档：显式 URL 生效，且 SQLite 路径置空", () => {
  const cfg = loadConfig({
    [ENV_KEYS.mode]: "server",
    [ENV_KEYS.databaseUrl]: "postgres://u:p@h:5432/db",
  });
  assert.equal(cfg.mode, "server");
  assert.equal(cfg.databaseUrl, "postgres://u:p@h:5432/db");
  assert.equal(cfg.sqlitePath, null);
});

test("server 档缺 DATABASE_URL：抛 ConfigError 并列出缺失键", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.mode]: "server" }),
    (error) => {
      assert.ok(error instanceof ConfigError);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.deepEqual(error.missingKeys, [ENV_KEYS.databaseUrl]);
      assert.equal(error.httpStatus, 422);
      return true;
    },
  );
});

test("档位非法：抛 ConfigError（不是静默回落到 local）", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.mode]: "cloud" }),
    (error) => {
      assert.ok(error instanceof ConfigError);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      return true;
    },
  );
});

test("空串环境变量按「未提供」处理", () => {
  const cfg = loadConfig({ [ENV_KEYS.mode]: "" });
  assert.equal(cfg.mode, "local");
});

test("tryLoadConfig：缺配置返回 null，不抛", () => {
  assert.equal(tryLoadConfig({ [ENV_KEYS.mode]: "server" }), null);
});

// ---------------------------------------------------------------------------
// logJson：`WBTIME_LOG_JSON` 必须是**活配置**（过去被 `mode === "server"` 硬编码顶掉）
// ---------------------------------------------------------------------------

test("logJson 缺省值随档位：local 关、server 开", () => {
  assert.equal(loadConfig({}).logJson, false, "local 档缺省不写 JSON 日志");
  assert.equal(
    loadConfig({
      [ENV_KEYS.mode]: "server",
      [ENV_KEYS.databaseUrl]: "postgres://u:p@h:5432/db",
    }).logJson,
    true,
    "server 档缺省写 JSON 日志（容器采集口径）",
  );
});

test("logJson 可被 WBTIME_LOG_JSON 双向覆盖（配置不再被档位硬编码顶掉）", () => {
  assert.equal(
    loadConfig({
      [ENV_KEYS.mode]: "server",
      [ENV_KEYS.databaseUrl]: "postgres://u:p@h:5432/db",
      [ENV_KEYS.logJson]: "false",
    }).logJson,
    false,
    "server 档显式关掉 JSON 日志必须生效",
  );
  assert.equal(
    loadConfig({ [ENV_KEYS.logJson]: "true" }).logJson,
    true,
    "local 档显式打开 JSON 日志必须生效",
  );
});

test("logJson 取值非法：抛 ConfigError（与缺配置同一错误形态）", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.logJson]: "maybe" }),
    (error) => {
      assert.ok(error instanceof ConfigError, "必须是 ConfigError，不是 TypeError");
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.equal(error.httpStatus, 422);
      assert.match(error.message, /WBTIME_LOG_JSON/, "消息里必须带键名");
      assert.match(error.message, /maybe/, "消息里必须带原始值");
      return true;
    },
  );
});

test("端口取值非法：抛 ConfigError（不是 TypeError —— 启动期只允许一种错误形态）", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.port]: "abc" }),
    (error) => {
      assert.ok(error instanceof ConfigError, "必须是 ConfigError，不是 TypeError");
      assert.equal(error instanceof TypeError, false);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.match(error.message, /WBTIME_API_PORT/);
      assert.match(error.message, /abc/);
      return true;
    },
  );
});

// ---------------------------------------------------------------------------
// shutdownTimeoutMs（FIX-07）：优雅关闭的兜底时长必须是**活配置**
// ---------------------------------------------------------------------------

test("shutdownTimeoutMs：缺省 10_000ms（兜底必须默认生效，不能靠部署方记得配）", () => {
  assert.equal(loadConfig({}).shutdownTimeoutMs, 10000);
});

test("shutdownTimeoutMs：显式取值生效，`0` 表示不设兜底（合法）", () => {
  assert.equal(loadConfig({ [ENV_KEYS.shutdownTimeoutMs]: "2500" }).shutdownTimeoutMs, 2500);
  assert.equal(loadConfig({ [ENV_KEYS.shutdownTimeoutMs]: "0" }).shutdownTimeoutMs, 0);
});

test("shutdownTimeoutMs：负数抛 ConfigError（无语义的值必须当场炸）", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.shutdownTimeoutMs]: "-1" }),
    (error) => {
      assert.ok(error instanceof ConfigError);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.match(error.message, /WBTIME_SHUTDOWN_TIMEOUT_MS/);
      return true;
    },
  );
});

test("shutdownTimeoutMs：非整数抛 ConfigError（与端口同一口径）", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.shutdownTimeoutMs]: "10s" }),
    (error) => {
      assert.ok(error instanceof ConfigError);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.match(error.message, /WBTIME_SHUTDOWN_TIMEOUT_MS/);
      return true;
    },
  );
});

// ---------------------------------------------------------------------------
// registerRateLimitPerMinute（FIX-04）：未认证注册的限速阈值
// ---------------------------------------------------------------------------

test("registerRateLimitPerMinute：缺省 20（限速必须默认生效，不能靠部署方记得配）", () => {
  assert.equal(loadConfig({}).registerRateLimitPerMinute, 20);
});

test("registerRateLimitPerMinute：显式取值生效，`0` 表示关闭（合法，仅测试）", () => {
  assert.equal(loadConfig({ [ENV_KEYS.registerRateLimitPerMinute]: "0" }).registerRateLimitPerMinute, 0);
  assert.equal(loadConfig({ [ENV_KEYS.registerRateLimitPerMinute]: "5" }).registerRateLimitPerMinute, 5);
});

test("registerRateLimitPerMinute：负数抛 ConfigError（无语义的值必须当场炸）", () => {
  assert.throws(
    () => loadConfig({ [ENV_KEYS.registerRateLimitPerMinute]: "-1" }),
    (error) => {
      assert.ok(error instanceof ConfigError);
      assert.equal(error.code, "CONFIGURATION_ERROR");
      assert.match(error.message, /WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE/);
      return true;
    },
  );
});

test("registerRateLimitPerMinute：非数字/非整数抛 ConfigError", () => {
  for (const raw of ["abc", "1.5", ""]) {
    if (raw === "") {
      // 空串按「未提供」处理 ⇒ 回落默认值（与 readEnv 的既有口径一致）
      assert.equal(loadConfig({ [ENV_KEYS.registerRateLimitPerMinute]: raw }).registerRateLimitPerMinute, 20);
      continue;
    }
    assert.throws(
      () => loadConfig({ [ENV_KEYS.registerRateLimitPerMinute]: raw }),
      (error) => {
        assert.ok(error instanceof ConfigError, `${raw} 必须抛 ConfigError`);
        assert.equal(error.code, "CONFIGURATION_ERROR");
        assert.match(error.message, /WBTIME_REGISTER_RATE_LIMIT_PER_MINUTE/);
        return true;
      },
    );
  }
});
