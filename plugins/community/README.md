# 社区插件目录（`plugins/community/`）

本目录存放 **社区（community）** 插件。目录约定（W1b 裁定 §3.2 / T2-05）：

- **每个子目录 = 一个插件**（`.gitkeep` 占位，非插件）；
- 子目录内需含 **`plugin.toml`** 元数据清单 + Python 包；
- 元数据键（`plugin.toml`）：
  - `name`：插件名（唯一键）；
  - `version`：版本；
  - `kind`：应为 `"community"`；
  - `entry_point = "module:attr"`（或 `module` + 可选 `attr`，默认 `"plugin"`）；
  - `description` / `permissions`（可选）。
- 插件须暴露符合 `astra_plugin.metadata.Plugin` 的对象（具备 `metadata` /
  `register(registrar)` / `unregister()`）。

装载入口：`astra_plugin.loader.PluginLoader`（entry point group = `astra.plugins`
+ 目录扫描）。单插件加载失败 → 结构化 `ERROR` + 跳过（不阻断启动）；CLI 命令冲突
→ `DomainError(CONFLICT)`（启动失败，不静默覆盖）。

> 🔴 本阶段（W1b / T2-05）**只定义目录约定与装载机制**；社区插件实现归 Phase 3+。
