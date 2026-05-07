import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ToolHint, ToolHintInput } from '@/lib/toolHintSchema';

const QK = ['toolHints'] as const;

export function useToolHints() {
  return useQuery({
    queryKey: QK,
    queryFn: () => api.get<ToolHint[]>('/admin/api/tool-hints'),
  });
}

export function useUpsertToolHint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      tool_name,
      interpretation_hint,
      usage_rules,
      data_sensitivity,
    }: ToolHintInput) =>
      api.put<ToolHint>(`/admin/api/tool-hints/${encodeURI(tool_name)}`, {
        interpretation_hint,
        usage_rules,
        data_sensitivity,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
