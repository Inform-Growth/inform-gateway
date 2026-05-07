import { z } from 'zod';

/**
 * Shape used by the Settings form. The backend stores org_profile as free-form
 * JSON; this schema is what the UI commits to. Adding a field here = adding a
 * field to the form. The PUT endpoint accepts whatever we send.
 */
export const orgProfileSchema = z.object({
  display_name: z.string().max(120, 'Keep it under 120 characters').default(''),
  tone:         z.string().max(200).default(''),
  icp:          z.string().max(200).default(''),
  vocab_rules:  z.string().max(2000).default(''),
});

export type OrgProfile = z.infer<typeof orgProfileSchema>;

/** Response shape for GET /admin/api/org-profile */
export type OrgProfileResponse = {
  org_id: string;
  initialized: boolean;
  profile: Partial<OrgProfile> | null;
};

/** Response shape for PUT /admin/api/org-profile */
export type OrgProfileUpdateResponse = {
  org_id: string;
  profile: OrgProfile;
};

/** Coerce an unknown server profile to a fully-populated form value. */
export function profileFromServer(p: Partial<OrgProfile> | null | undefined): OrgProfile {
  return orgProfileSchema.parse({
    display_name: p?.display_name ?? '',
    tone:         p?.tone ?? '',
    icp:          p?.icp ?? '',
    vocab_rules:  p?.vocab_rules ?? '',
  });
}
