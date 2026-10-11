"""``Embedder``（复用 ``ModelProvider.embeddings()``；显式路由 + 维度校验；W5 / T2-29）。

- **接口不变**：仅复用 ``ModelProvider.embeddings(texts, **options) -> list[Embedding]``；
- **显式路由（P1-a）**：经注入的 :class:`~astra_model.ModelRouter` 解析
  ``kb.embedding_model = {provider, model, dimensions}``；解析失败即抛
  （``CONFIGURATION_ERROR``，**不静默 fallback**）；
- **维度不匹配即拒（I-P2-25）**：``kb.embedding_model.dimensions`` 须等于部署级
  ``capability.embedding_dimensions``；返回向量长度不符 → ``VALIDATION_ERROR``
  （``reason="embedding_dimension_mismatch"``）。

🔴 本模块**零 Web / ORM**。
"""

from __future__ import annotations

from collections.abc import Sequence

from astra_core import DomainError, ErrorCode
from astra_model import ModelRouter

from .domain import KnowledgeBase

__all__ = ["Embedder", "DEFAULT_EMBEDDING_DIMENSIONS"]

#: 默认部署级嵌入维度（＝ ``capability.embedding_dimensions`` / ``embedding.vector`` 列维度）。
DEFAULT_EMBEDDING_DIMENSIONS = 1536


class Embedder:
    """文本嵌入器（批处理 + 维度校验 + 显式路由）。

    Args:
        model_router: 显式 Model Router（按 ``kb.embedding_model`` 解析 Provider）。
        embedding_dimensions: 部署级固定维度（＝ ``capability.embedding_dimensions``）。
    """

    def __init__(
        self, *, model_router: ModelRouter, embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    ) -> None:
        self._router = model_router
        self._dimensions = int(embedding_dimensions)

    @property
    def embedding_dimensions(self) -> int:
        """部署级固定维度。"""
        return self._dimensions

    def embed(self, texts: Sequence[str], *, kb: KnowledgeBase) -> list[list[float]]:
        """对一批文本计算嵌入向量（按输入顺序返回）。

        Args:
            texts: 待嵌入文本序列。
            kb: 知识库（提供 ``embedding_model`` 显式路由配置）。

        Returns:
            向量列表（每项长度 ＝ 部署级维度）。

        Raises:
            DomainError: ``kb`` 维度与部署级不符 / Provider 未注册 / 向量维度不符
                （``VALIDATION_ERROR`` / ``CONFIGURATION_ERROR``）。
        """
        items = list(texts)
        if not items:
            return []

        kb_dimensions = int((kb.embedding_model or {}).get("dimensions", self._dimensions))
        if kb_dimensions != self._dimensions:
            raise _dimension_error(
                reason="embedding_dimension_mismatch",
                expected=self._dimensions,
                actual=kb_dimensions,
            )

        resolved = self._router.resolve(dict(kb.embedding_model or {}))
        embeddings = resolved.provider.embeddings(items, model=resolved.model)
        ordered = sorted(embeddings, key=lambda item: item.index)

        vectors: list[list[float]] = []
        for embedding in ordered:
            vector = [float(value) for value in embedding.vector]
            if len(vector) != self._dimensions:
                raise _dimension_error(
                    reason="embedding_dimension_mismatch",
                    expected=self._dimensions,
                    actual=len(vector),
                )
            vectors.append(vector)
        return vectors


def _dimension_error(*, reason: str, expected: int, actual: int) -> DomainError:
    """构造维度不匹配异常（``VALIDATION_ERROR``）。"""
    return DomainError(
        f"嵌入维度不匹配：期望 {expected}，实际 {actual}",
        code=ErrorCode.VALIDATION_ERROR,
        data={"reason": reason, "expected": expected, "actual": actual},
    )
