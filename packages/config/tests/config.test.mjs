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
