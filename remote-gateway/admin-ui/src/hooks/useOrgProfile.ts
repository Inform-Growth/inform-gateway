import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import {
  type OrgProfile,
  type OrgProfileResponse,
  type OrgProfileUpdateResponse,
  profileFromServer,
} from '@/lib/orgProfileSchema';

const QUERY_KEY = ['orgProfile'] as const;

export function useOrgProfile() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<OrgProfile> => {
      const res = await api.get<OrgProfileResponse>('/admin/api/org-profile');
      return profileFromServer(res.profile);
    },
  });
}

export function useUpdateOrgProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (next: OrgProfile) =>
      api.put<OrgProfileUpdateResponse>('/admin/api/org-profile', next),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
