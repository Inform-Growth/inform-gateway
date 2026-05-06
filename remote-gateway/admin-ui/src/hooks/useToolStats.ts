import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type ToolStat = {
  name: string;
  call_count: number;
  error_count: number;
  error_rate: string;
  last_called: string | null;
  avg_duration_ms: number;
  max_duration_ms: number;
  avg_response_size: number;
  max_response_size: number;
  avg_input_size: number;
  max_input_size: number;
};

type StatsResponse = { tools: ToolStat[]; summary?: unknown; error?: string };

export function useToolStats() {
  return useQuery({
    queryKey: ['toolStats'],
    queryFn: async (): Promise<ToolStat[]> => {
      const res = await api.get<StatsResponse>('/admin/api/stats');
      return res.tools ?? [];
    },
  });
}
