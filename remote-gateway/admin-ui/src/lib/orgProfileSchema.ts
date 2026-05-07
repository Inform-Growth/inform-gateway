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

/** Coerce an unknown server profile to a fully-populated form value.
 *
 * Server data is free-form JSON — fields may be missing, non-string, or
 * longer than the form's max-length validators. Rather than throwing (which
 * would make the Settings page unloadable), coerce non-strings to '' and
 * truncate to the per-field limit. The form's submit-time schema still
 * enforces the limits when the user saves.
 */
export function profileFromServer(p: Partial<OrgProfile> | null | undefined): OrgProfile {
  const safeStr = (v: unknown, max: number): string =>
    typeof v === 'string' ? v.slice(0, max) : '';
  const raw = (p ?? {}) as Record<string, unknown>;
  return {
    display_name: safeStr(raw.display_name, 120),
    tone:         safeStr(raw.tone, 200),
    icp:          safeStr(raw.icp, 200),
    vocab_rules:  safeStr(raw.vocab_rules, 2000),
  };
}
