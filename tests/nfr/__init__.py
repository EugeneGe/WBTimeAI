"""NFR 基线测试包（W8 / T1-38；设计 §3.1 ``N-P1-01``~``N-P1-08``）。

本包为**非功能基线**测试（性能 / 并发 / 数据保留与清理），性质为 nightly（软失败出
报告、**超基线即红**），见 ``.github/workflows/nfr.yml``：

- :mod:`tests.nfr.test_perf_baseline`：``N-P1-01``（50 并发 SSE p95 首帧 + 1000 条事件批量写入）；
- :mod:`tests.nfr.test_concurrency`：``N-P1-02``（同会话活跃 Run 上界 + 并发无丢失 / 无重复）；
- :mod:`tests.nfr.test_retention_stub`：``N-P1-06``（全量落库 + 清理任务预留）。
"""
