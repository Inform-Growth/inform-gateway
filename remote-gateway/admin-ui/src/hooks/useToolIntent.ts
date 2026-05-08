import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type ToolIntentRow = {
  tool_name: string;
  requires_intent: boolean;
  locked: boolean;
  explicit: boolean;
};

type ToolIntentResponse = { user_id: string; overrides: ToolIntentRow[] };

const KEY = (userId: string) => ['tool-intent', userId] as const;

export function useToolIntent(userId: string | null) {
  return useQuery({
    queryKey: userId ? KEY(userId) : ['tool-intent', '__none__'],
    enabled: !!userId,
    queryFn: async (): Promise<ToolIntentRow[]> => {
      const res = await api.get<ToolIntentResponse>(
        `/admin/api/tool-intent/${encodeURIComponent(userId!)}`,
      );
      return res.overrides;
    },
  });
}

export function useSetToolIntent(userId: string) {
  const qc = useQueryClient();
  const queryKey = KEY(userId);

  return useMutation({
    mutationFn: ({ tool_name, requires_intent }: { tool_name: string; requires_intent: boolean }) =>
      api.put(
        `/admin/api/tool-intent/${encodeURIComponent(userId)}/${encodeURI(tool_name)}`,
        { requires_intent },
      ),
    onSettled: () => qc.invalidateQueries({ queryKey }),
  });
}

export function useClearToolIntent(userId: string) {
  const qc = useQueryClient();
  const queryKey = KEY(userId);

  return useMutation({
    mutationFn: (tool_name: string) =>
      api.delete(
        `/admin/api/tool-intent/${encodeURIComponent(userId)}/${encodeURI(tool_name)}`,
      ),
    onSettled: () => qc.invalidateQueries({ queryKey }),
  });
}
