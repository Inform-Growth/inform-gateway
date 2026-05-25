import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export type Role = 'user' | 'admin';

export type Operator = {
  user_id: string;
  key: string;          // redacted preview
  role: Role;
  call_count: number;
  last_active: string | null;
  [extra: string]: unknown;
};

export type CreateOperatorResponse = {
  user_id: string;
  key: string;          // FULL plaintext — only present in this response
};

const QUERY_KEY = ['operators'] as const;

export function useOperators() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => api.get<Operator[]>('/admin/api/users'),
  });
}

export function useCreateOperator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (user_id: string) =>
      api.post<CreateOperatorResponse>('/admin/api/users', { user_id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeleteOperator() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (user_id: string) =>
      api.delete<{ deleted: number; user_id: string }>(
        `/admin/api/users/${encodeURIComponent(user_id)}`,
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useSetUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ user_id, role }: { user_id: string; role: Role }) =>
      api.put<{ ok: boolean; user_id: string; role: Role }>(
        `/admin/api/users/${encodeURIComponent(user_id)}/role`,
        { role },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
