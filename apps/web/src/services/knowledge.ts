import { api } from "@/lib/api";
import type {
  CreateDocumentRequest,
  CreateKnowledgeBaseRequest,
  DocumentResponse,
  KnowledgeBaseResponse,
  SearchRequest,
  SearchResponse,
  UpdateKnowledgeBaseRequest,
} from "@/types";

/**
 * Knowledge 服务（`/knowledge/*` API，W6 / T2-35；设计 §2.6 / §2.12）。
 *
 * - 知识库：列表 / 详情 / 创建 / 更新（B-19a）/ 删除（B-19a）；
 * - 文档：列表（携 `status` 供展示索引进度）/ 登记；
 * - 检索试跑：`search`（命中 + 引用 + 检索路 `mode`）。
 *
 * 🔴 统一响应壳由 `lib/api.ts` 拦截器解壳，本层直接拿业务 DTO。
 */
export const knowledgeService = {
  /** 知识库列表。 */
  listBases(): Promise<KnowledgeBaseResponse[]> {
    return api.get<KnowledgeBaseResponse[]>("/knowledge/bases").then((r) => r.data);
  },
  /** 知识库详情。 */
  getBase(knowledgeBaseId: string): Promise<KnowledgeBaseResponse> {
    return api
      .get<KnowledgeBaseResponse>(`/knowledge/bases/${knowledgeBaseId}`)
      .then((r) => r.data);
  },
  /** 创建知识库。 */
  createBase(payload: CreateKnowledgeBaseRequest): Promise<KnowledgeBaseResponse> {
    return api.post<KnowledgeBaseResponse>("/knowledge/bases", payload).then((r) => r.data);
  },
  /** 更新知识库（改名 / 描述；B-19a）。 */
  updateBase(
    knowledgeBaseId: string,
    payload: UpdateKnowledgeBaseRequest,
  ): Promise<KnowledgeBaseResponse> {
    return api
      .patch<KnowledgeBaseResponse>(`/knowledge/bases/${knowledgeBaseId}`, payload)
      .then((r) => r.data);
  },
  /** 删除知识库（后端级联删除文档 / 分块 / 向量 / 绑定；B-19a）。 */
  async deleteBase(knowledgeBaseId: string): Promise<void> {
    await api.delete(`/knowledge/bases/${knowledgeBaseId}`);
  },
  /** 某知识库下的文档列表。 */
  listDocuments(knowledgeBaseId: string): Promise<DocumentResponse[]> {
    return api
      .get<DocumentResponse[]>(`/knowledge/bases/${knowledgeBaseId}/documents`)
      .then((r) => r.data);
  },
  /** 登记文档（初始 `PENDING`）。 */
  createDocument(
    knowledgeBaseId: string,
    payload: CreateDocumentRequest,
  ): Promise<DocumentResponse> {
    return api
      .post<DocumentResponse>(`/knowledge/bases/${knowledgeBaseId}/documents`, payload)
      .then((r) => r.data);
  },
  /** 检索试跑（命中 + 引用 + 检索路 `mode`）。 */
  search(payload: SearchRequest): Promise<SearchResponse> {
    return api.post<SearchResponse>("/knowledge/search", payload).then((r) => r.data);
  },
};
