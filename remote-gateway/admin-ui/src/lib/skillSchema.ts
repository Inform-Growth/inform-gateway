import { z } from 'zod';

export const skillSchema = z.object({
  name: z
    .string()
    .min(1, 'Required')
    .max(80, 'Keep it under 80 chars')
    .regex(/^[a-z0-9_]+$/, 'lowercase letters, digits, and underscores only'),
  description: z.string().min(1, 'Required').max(200),
  prompt_template: z.string().min(1, 'Required').max(8000),
});

export type SkillInput = z.infer<typeof skillSchema>;

export type Skill = SkillInput & {
  id: string;
  is_system: 0 | 1 | boolean;
  created_by: string | null;
  created_at: string | number;
  updated_at: string | number;
};

export const isSystemSkill = (s: Skill) => s.is_system === 1 || s.is_system === true;
