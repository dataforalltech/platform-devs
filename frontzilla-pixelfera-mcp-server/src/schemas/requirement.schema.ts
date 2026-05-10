import { z } from 'zod';
import { DetailLevelSchema } from '../utils/validators.js';

export const AnalyzeRequirementSchema = z.object({
  requirement: z.string().min(10),
  context: z.string().optional(),
});

export const SplitTasksSchema = z.object({
  feature_id: z.string().startsWith('feat_'),
});

export const GenerateFeatureSpecSchema = z.object({
  feature_id: z.string().startsWith('feat_'),
  detail_level: DetailLevelSchema,
});

export const GenerateScreenBriefSchema = z.object({
  feature_id: z.string().startsWith('feat_'),
  screen_name: z.string().min(3),
});

export const AnalysisResultSchema = z.object({
  screens: z.array(z.string()),
  flows: z.array(z.object({
    name: z.string(),
    steps: z.array(z.string()),
  })),
  actors: z.array(z.string()),
  complexity: z.enum(['low', 'medium', 'high']),
  estimated_effort_hours: z.number().positive(),
});

export const FeatureSpecSchema = z.object({
  wireframe_hints: z.array(z.string()),
  api_contracts: z.array(z.object({
    endpoint: z.string(),
    method: z.enum(['GET', 'POST', 'PUT', 'DELETE', 'PATCH']),
    request_schema: z.record(z.unknown()),
    response_schema: z.record(z.unknown()),
  })),
  component_list: z.array(z.string()),
  design_system_requirements: z.record(z.unknown()).optional(),
});

export const ScreenBriefSchema = z.object({
  layout: z.string(),
  states: z.array(z.object({
    name: z.string(),
    description: z.string(),
  })),
  interactions: z.array(z.object({
    trigger: z.string(),
    action: z.string(),
    result: z.string(),
  })),
  data_bindings: z.array(z.object({
    element: z.string(),
    source: z.string(),
  })).optional(),
});

export type AnalyzeRequirementInput = z.infer<typeof AnalyzeRequirementSchema>;
export type SplitTasksInput = z.infer<typeof SplitTasksSchema>;
export type GenerateFeatureSpecInput = z.infer<typeof GenerateFeatureSpecSchema>;
export type GenerateScreenBriefInput = z.infer<typeof GenerateScreenBriefSchema>;
export type AnalysisResult = z.infer<typeof AnalysisResultSchema>;
export type FeatureSpec = z.infer<typeof FeatureSpecSchema>;
export type ScreenBrief = z.infer<typeof ScreenBriefSchema>;
