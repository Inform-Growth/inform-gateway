import { z } from 'zod';

export const SENSITIVITIES = ['public', 'internal', 'sensitive'] as const;

export const toolHintSchema = z.object({
  tool_name: z.string().min(1, 'Required').max(120),
  interpretation_hint: z.string().max(2000).default(''),
  usage_rules: z.string().max(2000).default(''),
  data_sensitivity: z.enum(SENSITIVITIES).default('internal'),
});

export type ToolHintInput = z.infer<typeof toolHintSchema>;
export type ToolHint = ToolHintInput;
