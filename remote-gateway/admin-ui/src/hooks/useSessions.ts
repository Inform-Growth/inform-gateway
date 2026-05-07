import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type SankeyNode = { id: string; name: string };
export type SankeyLink = { source: string; target: string; value: number };

export type SessionsData = {
  sankey: { nodes: SankeyNode[]; links: SankeyLink[] };
  user_breakdown: Record<string, number>;
};

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: async (): Promise<SessionsData> => {
      const res = await api.get<{
        sankey?: { nodes?: SankeyNode[]; links?: SankeyLink[] };
        user_breakdown?: Record<string, number>;
      }>('/admin/api/sessions');
      return {
        sankey: {
          nodes: res.sankey?.nodes ?? [],
          links: res.sankey?.links ?? [],
        },
        user_breakdown: res.user_breakdown ?? {},
      };
    },
  });
}
