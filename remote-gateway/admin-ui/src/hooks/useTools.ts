import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';

export type ToolMeta = { name: string; description: string };

export function useTools() {
  return useQuery({
    queryKey: ['tools'],
    queryFn: async (): Promise<ToolMeta[]> => {
      try {
        return await api.get<ToolMeta[]>('/admin/api/tools');
      } catch (err) {
        // 503 means list_tools_fn isn't wired — treat as empty rather than error.
        if (err instanceof ApiError && err.status === 503) return [];
        throw err;
      }
    },
  });
}
