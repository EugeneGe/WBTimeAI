import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/lib/query";
import { skillService } from "@/services/skill";
import { useAuthStore } from "@/stores/authStore";
import type { CreateSkillRequest, CreateSkillVersionRequest, UpdateSkillRequest } from "@/types";

/**
 * Skill hooks（TanStack Query；W3 / T2-18；设计 §2.3）。
 *
 * 服务状态唯一真相源；`enabled` 依认证态（对齐 `hooks/useTools.ts` 范式）。
 */

/** Skill 列表。 */
export function useSkills() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return useQuery({
    queryKey: queryKeys.skills,
    queryFn: () => skillService.list(),
    enabled: isAuthenticated,
  });
}

/** Skill 详情（`skillId` 为空时不请求）。 */
export function useSkill(skillId: string | null) {
  return useQuery({
    queryKey: queryKeys.skill(skillId ?? ""),
    queryFn: () => skillService.get(skillId as string),
    enabled: Boolean(skillId),
  });
}

/** Skill 版本列表（`skillId` 为空时不请求）。 */
export function useSkillVersions(skillId: string | null) {
  return useQuery({
    queryKey: queryKeys.skillVersions(skillId ?? ""),
    queryFn: () => skillService.listVersions(skillId as string),
    enabled: Boolean(skillId),
  });
}

/** 创建 Skill mutation。 */
export function useCreateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateSkillRequest) => skillService.create(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills });
    },
  });
}

/** 更新 Skill mutation。 */
export function useUpdateSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, payload }: { skillId: string; payload: UpdateSkillRequest }) =>
      skillService.update(skillId, payload),
    onSuccess: (skill) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(skill.id) });
    },
  });
}

/** 创建 Skill 版本 mutation。 */
export function useCreateSkillVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, payload }: { skillId: string; payload: CreateSkillVersionRequest }) =>
      skillService.createVersion(skillId, payload),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillVersions(version.skill_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(version.skill_id) });
    },
  });
}

/** 发布 Skill 版本 mutation。 */
export function usePublishSkill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) => skillService.publish(skillId),
    onSuccess: (version) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(version.skill_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillVersions(version.skill_id) });
    },
  });
}
