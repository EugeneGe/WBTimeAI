"""``tests/security`` 包（R5 / T2-63）：远程工作站的**安全边界**独立测试。

与 ``tests/integration/workspace/test_apply_push_safety.py``（功能安全）**互补**：本包聚焦
「越权 / 逃逸 / 泄漏 / 绕过」四类**边界不变量**（设计 §3 #36 / #38 / #39 / #42；N5 / D17 / D19），
把 B1A~B3C / R4 各阶段 QA 自研探针的口径**沉淀为正式回归**。
"""
