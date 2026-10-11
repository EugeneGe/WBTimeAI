import { api } from "@/lib/api";
import type {
  CreateSkillRequest,
  CreateSkillVersionRequest,
  SkillResponse,
  SkillVersionResponse,
  UpdateSkillRequest,
} from "@/types";

/**
 * Skill 服务（`/skills/*` API，W3 / T2-18；设计 §2.3 / §2.12）。
 *
 * - CRUD：创建 / 列表 / 详情 / 更新；
 * - 版本：创建 / 列表；
 * - 发布：把最新 `DRAFT` 版本冻结为 `PUBLISHED`（`current_version_id` 更新）。
 */
export const skillService = {
  /** Skill 列表（当前租户）。 */
  list(): Promise<SkillResponse[]> {
    return api.get<SkillResponse[]>("/skills").then((r) => r.data);
  },
  /** Skill 详情。 */
  get(skillId: string): Promise<SkillResponse> {
    return api.get<SkillResponse>(`/skills/${skillId}`).then((r) => r.data);
  },
  /** 创建 Skill。 */
  create(payload: CreateSkillRequest): Promise<SkillResponse> {
    return api.post<SkillResponse>("/skills", payload).then((r) => r.data);
  },
  /** 更新 Skill 元数据（仅提供需变更字段）。 */
  update(skillId: string, payload: UpdateSkillRequest): Promise<SkillResponse> {
    return api.put<SkillResponse>(`/skills/${skillId}`, payload).then((r) => r.data);
  },
  /** Skill 版本列表。 */
  listVersions(skillId: string): Promise<SkillVersionResponse[]> {
    return api.get<SkillVersionResponse[]>(`/skills/${skillId}/versions`).then((r) => r.data);
  },
  /** 创建 Skill 版本（`DRAFT`）。 */
  createVersion(
    skillId: string,
    payload: CreateSkillVersionRequest,
  ): Promise<SkillVersionResponse> {
    return api
      .post<SkillVersionResponse>(`/skills/${skillId}/versions`, payload)
      .then((r) => r.data);
  },
  /** 发布 Skill 最新的 `DRAFT` 版本。 */
  publish(skillId: string): Promise<SkillVersionResponse> {
    return api.post<SkillVersionResponse>(`/skills/${skillId}/publish`).then((r) => r.data);
  },
};
