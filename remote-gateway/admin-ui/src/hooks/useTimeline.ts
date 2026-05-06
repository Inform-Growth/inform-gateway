import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

type TimelineRow = { day: string; [user: string]: number | string };
type TimelineResponse = { users: string[]; days: TimelineRow[] };

export type TimelineData = {
  users: string[];
  rows: TimelineRow[];                      // raw per-user breakdown (kept for future use)
  totals: { day: string; total: number }[]; // sum across users per day
};

export function useTimeline(days: number) {
  return useQuery({
    queryKey: ['timeline', days],
    queryFn: async (): Promise<TimelineData> => {
      const res = await api.get<TimelineResponse>('/admin/api/timeline', { days });
      const totals = res.days.map((row) => {
        let sum = 0;
        for (const user of res.users) {
          const v = row[user];
          if (typeof v === 'number') sum += v;
        }
        return { day: row.day, total: sum };
      });
      return { users: res.users, rows: res.days, totals };
    },
  });
}
