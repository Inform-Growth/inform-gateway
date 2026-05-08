import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type SkillPermission = { skill_name: string; enabled: boolean };

type SkillPermissionsResponse = { user_id: string; permissions: SkillPermission[] };

const KEY = (userId: string) => ['skill-permissions', userId] as const;

export function useSkillPermissions(userId: string | null) {
  return useQuery({
    queryKey: userId ? KEY(userId) : ['skill-permissions', '__none__'],
    enabled: !!userId,
    queryFn: async (): Promise<SkillPermission[]> => {
      const res = await api.get<SkillPermissionsResponse>(
        `/admin/api/skill-permissions/${encodeURIComponent(userId!)}`,
      );
      return res.permissions;
    },
  });
}

export function useSetSkillPermission(userId: string) {
  const qc = useQueryClient();
  const queryKey = KEY(userId);

  return useMutation({
    mutationFn: ({ skill_name, enabled }: SkillPermission) =>
      api.put(
        `/admin/api/skill-permissions/${encodeURIComponent(userId)}/${encodeURI(skill_name)}`,
        { enabled },
      ),
    onMutate: async ({ skill_name, enabled }) => {
      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<SkillPermission[]>(queryKey);
      if (previous) {
        qc.setQueryData<SkillPermission[]>(
          queryKey,
          previous.map((p) => (p.skill_name === skill_name ? { ...p, enabled } : p)),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKey, ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey }),
  });
}
