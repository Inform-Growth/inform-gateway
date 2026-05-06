import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type StatsSummary = {
  total_calls: number;
  total_tools_seen: number;
  high_error_rate: string[];
};

type StatsResponse = {
  tools?: unknown[];
  summary?: Partial<StatsSummary>;
  error?: string;
};

const EMPTY: StatsSummary = { total_calls: 0, total_tools_seen: 0, high_error_rate: [] };

export function useStatsSummary() {
  return useQuery({
    queryKey: ['statsSummary'],
    queryFn: async (): Promise<StatsSummary> => {
      const res = await api.get<StatsResponse>('/admin/api/stats');
      const s = res.summary;
      if (!s) return EMPTY;
      return {
        total_calls: s.total_calls ?? 0,
        total_tools_seen: s.total_tools_seen ?? 0,
        high_error_rate: s.high_error_rate ?? [],
      };
    },
  });
}
