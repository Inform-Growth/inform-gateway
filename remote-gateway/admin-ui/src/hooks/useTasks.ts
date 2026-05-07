import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type Task = {
  task_id: string;
  user_id: string;
  org_id: string;
  goal: string;
  steps: unknown[] | null;
  status: 'active' | 'complete';
  outcome: string | null;
  created_at: number | string;
  completed_at: number | string | null;
};

type TasksResponse = { org_id: string; tasks: Task[]; count: number };

export type TasksFilters = {
  status?: 'active' | 'complete' | '';
  limit?: number;
};

export function useTasks(filters: TasksFilters) {
  const params: Record<string, string | number> = {};
  if (filters.status) params.status = filters.status;
  if (filters.limit) params.limit = filters.limit;

  return useQuery({
    queryKey: ['tasks', filters],
    queryFn: async () => {
      const res = await api.get<TasksResponse>('/admin/api/tasks', params);
      return res.tasks;
    },
  });
}
