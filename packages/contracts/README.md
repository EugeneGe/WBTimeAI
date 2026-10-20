# `@wbtime/contracts`（V0.1.0 · T1-04）

9 个插件扩展点的 **interface 声明**（纯类型，无 loader）。

## 1. 本版做 / 不做

| | 内容 |
|---|---|
| **做** | 9 个扩展点的 `interface` + 版本常量（`<point>/vN`）+ 扩展点**类型级**注册表 + 领域类型名义占位 + 签名全等门禁 |
| **不做** | loader / 签名信任 / 沙箱装载 / Marketplace / 注册与兼容判定 —— **全部归 `V0.7.0`**（路线图 §3.1 M-05 **E-3**；施工任务划分 §1 禁令 ④） |

> 旧线 `extension_points/__init__.py:52-63` 的 `SUPPORTED_EXTENSION_POINTS` 是**运行时 dict**、
> `is_compatible_point()` 是**运行时判定函数**——两者都属运行面，本包**不提供**；
> `ExtensionPointRegistry` 是它们的**类型级**对应物（编译期存在，运行时不存在）。

## 2. 9 个扩展点（实测，非估算）

证据：`D:/WBT/WBTimeAI_old/packages/plugin/src/wbtime_ai_plugin/extension_points/`（9 个模块 + `__init__.py:52-63` 的 9 键映射）。

| # | 扩展点 | 版本常量 | interface | 成员数 |
|---|---|---|---|---|
| ① | `auth_provider` | `AUTH_PROVIDER_VERSION` | `AuthProvider` | 3 |
| ② | `policy_engine` | `POLICY_ENGINE_VERSION` | `PolicyEngine` | 2 |
| ③ | `audit_sink` | `AUDIT_SINK_VERSION` | `AuditSink` | 3 |
| ④ | `secret_provider` | `SECRET_PROVIDER_VERSION` | `SecretProvider` | 4 |
| ⑤ | `model_gateway` | `MODEL_GATEWAY_VERSION` | `ModelGateway` | 2 |
| ⑥ | `model_provider` | `MODEL_PROVIDER_VERSION` | `ModelProviderFactory` | 3 |
| ⑦ | `connector` | `CONNECTOR_VERSION` | `Connector` | 5 |
| ⑧ | `ui_extension` | `UI_EXTENSION_VERSION` | `UIExtension` | 2 |
| ⑨ | `agent_executor` | `AGENT_EXECUTOR_VERSION` | `AgentExecutor` | 7 |

> 成员数与签名**以门禁实测输出为准**（`python scripts/check_extension_point_signatures.py`），
> 上表是快照，不是第二真相源。

## 3. 签名全等门禁（E-3）

```bash
python scripts/check_extension_point_signatures.py            # 实跑
python scripts/check_extension_point_signatures.py --self-test # 8 条反例注入
python scripts/check_extension_point_signatures.py --write-snapshot  # 改接口后重生成快照
python scripts/check_extension_point_signatures.py --json      # 机器可读报告
```

断言：9 点逐一「成员名集合 + 参数类型 + 返回类型 + 版本常量」与旧线 Protocol 全等；
`audit_sink` 额外比**第三面**——核心侧 `packages/audit/src/wbtime_ai_audit/sink.py:59` 的 `AuditSink`
（E-3 原文「`audit.Sink` 与 `contracts.audit_sink/v1` 签名全等」）。
空集合（0 点 / 0 成员 / 0 领域类型 / 旧线源缺失）**必红**，不折叠为单布尔。

## 4. 命名偏差（有意为之，已登记）

- **成员名沿用旧线 snake_case**（`master_key` / `assets_base_url` / `stream_events` …）：
  ABI 保真优先于 TS 命名风格，V0.7.0 是插件 ABI 唯一窗口。
- `bytes` ⇒ `Uint8Array`、`Exception` ⇒ `Error`、`Iterator[X]` ⇒ `IterableIterator[X]`：
  归一化映射表在门禁脚本 `TYPE_MAP` / `GENERIC_MAP`，两侧同一张表。
- `domain-refs.ts` 只声明**名义占位**（不复制字段）：真实结构归 `@wbtime/domain`，
  迁移时逐行改成 `export type { X } from "@wbtime/domain";`。
- **未建 `src/frozen/`**：实测 `contracts/` 冻结集内**没有**扩展点件（`grep -ril extension contracts/`
  只命中 DDL / errors / type-map），无可派生对象，故不建空目录充数。
