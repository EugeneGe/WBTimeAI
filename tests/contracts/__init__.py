"""Provider 契约套件包（T1-14）。

- 统一契约断言（chat / stream / embeddings / count_tokens）参数化覆盖**全部已注册 Provider**；
- 注册表扫描断言：新增 Provider 未纳入即失败；
- 录制回放（cassettes）不依赖真实网络；真实联调走 ``provider_live`` marker（默认不跑）。
"""
