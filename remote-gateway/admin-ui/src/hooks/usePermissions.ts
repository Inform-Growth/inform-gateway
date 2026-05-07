import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type Permission = { tool_name: string; enabled: boolean };

type PermissionsResponse = { user_id: string; permissions: Permission[] };

const KEY = (userId: string) => ['permissions', userId] as const;

export function usePermissions(userId: string | null) {
  return useQuery({
    queryKey: userId ? KEY(userId) : ['permissions', '__none__'],
    enabled: !!userId,
    queryFn: async (): Promise<Permission[]> => {
      const res = await api.get<PermissionsResponse>(
        `/admin/api/permissions/${encodeURIComponent(userId!)}`,
      );
      return res.permissions;
    },
  });
}

export function useSetPermission(userId: string) {
  const qc = useQueryClient();
  const queryKey = KEY(userId);

  return useMutation({
    mutationFn: ({ tool_name, enabled }: Permission) =>
      api.put(
        `/admin/api/permissions/${encodeURIComponent(userId)}/${encodeURI(tool_name)}`,
        { enabled },
      ),
    onMutate: async ({ tool_name, enabled }) => {
      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<Permission[]>(queryKey);
      if (previous) {
        qc.setQueryData<Permission[]>(
          queryKey,
          previous.map((p) => (p.tool_name === tool_name ? { ...p, enabled } : p)),
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
