import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Skill, SkillInput } from '@/lib/skillSchema';

const QK = ['skills'] as const;

export function useSkills() {
  return useQuery({
    queryKey: QK,
    queryFn: () => api.get<Skill[]>('/admin/api/skills'),
  });
}

export function useCreateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: SkillInput) => api.post<Skill>('/admin/api/skills', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}

export function useUpdateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, description, prompt_template }: SkillInput) =>
      api.put<Skill>(`/admin/api/skills/${encodeURIComponent(name)}`, {
        description,
        prompt_template,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.delete<{ deleted: string }>(`/admin/api/skills/${encodeURIComponent(name)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
