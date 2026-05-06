import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type ToolCall = {
  id: number;
  tool_name: string;
  called_at: string | null;
  duration_ms: number;
  success: boolean;
  error_type: string | null;
  error_message: string | null;
  user_id: string | null;
  request_id: string | null;
  response_size: number | null;
  input_size: number | null;
  input_body: string | null;
  response_preview: string | null;
  task_id: string | null;
};

export type ToolCallFilters = {
  limit: number;
  offset: number;
  tool?: string;
  user?: string;
  success?: 'true' | 'false' | '';
  error_type?: string;
  task_id?: string;
};

export function useToolCalls(filters: ToolCallFilters) {
  return useQuery({
    queryKey: ['toolCalls', filters],
    queryFn: () => {
      const params: Record<string, string | number> = {
        limit: filters.limit,
        offset: filters.offset,
      };
      if (filters.tool) params.tool = filters.tool;
      if (filters.user) params.user = filters.user;
      if (filters.success) params.success = filters.success;
      if (filters.error_type) params.error_type = filters.error_type;
      if (filters.task_id) params.task_id = filters.task_id;
      return api.get<ToolCall[]>('/admin/api/logs', params);
    },
    placeholderData: (prev) => prev,
  });
}
