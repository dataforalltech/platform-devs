import { z } from 'zod';
import { ComponentCategorySchema, ToneSchema } from '../utils/validators.js';

export const GenerateWireframeSchema = z.object({
  screen_name: z.string().min(3),
  feature_id: z.string().optional(),
  layout: z.enum(['single-column', 'two-column', 'three-column', 'grid', 'card']).optional(),
});

export const CreateDesignTokensSchema = z.object({
  feature_id: z.string().startsWith('feat_').optional(),
  brand: z.string().optional(),
  theme: z.enum(['light', 'dark', 'auto']).optional(),
});

export const SuggestUiComponentsSchema = z.object({
  screen_name: z.string().min(3),
  feature_id: z.string().optional(),
});

export const GenerateUxWritingSchema = z.object({
  context: z.string().min(10),
  tone: ToneSchema.optional(),
  elements: z.array(z.string()).optional(),
});

export const MapVisualStatesSchema = z.object({
  component_name: z.string().min(3),
  feature_id: z.string().optional(),
});

export const ReviewUiConsistencySchema = z.object({
  components: z.array(z.string()),
  design_system: z.record(z.unknown()).optional(),
});

export const ValidateVisualAccessibilitySchema = z.object({
  component_name: z.string().min(3),
  spec: z.record(z.unknown()).optional(),
});

export const WireframeSchema = z.object({
  ascii_diagram: z.string(),
  annotations: z.array(z.object({
    region: z.string(),
    description: z.string(),
  })),
  components_used: z.array(z.string()),
});

export const DesignTokensSchema = z.object({
  colors: z.record(z.string()),
  typography: z.record(z.object({
    family: z.string(),
    size: z.string(),
    weight: z.string(),
    line_height: z.string(),
  })),
  spacing: z.record(z.string()),
  shadows: z.record(z.string()),
  radius: z.record(z.string()),
  animation: z.record(z.string()),
});

export const ComponentSuggestionSchema = z.object({
  name: z.string(),
  category: ComponentCategorySchema,
  props: z.array(z.object({
    name: z.string(),
    type: z.string(),
    required: z.boolean(),
    default: z.unknown().optional(),
  })),
});

export const UxWritingSchema = z.object({
  labels: z.record(z.string()),
  error_messages: z.record(z.string()),
  cta_copy: z.array(z.object({
    action: z.string(),
    text: z.string(),
  })),
  empty_states: z.record(z.string()),
  tooltips: z.array(z.object({
    element: z.string(),
    text: z.string(),
  })).optional(),
});

export const VisualStateSchema = z.object({
  name: z.string(),
  properties: z.record(z.unknown()),
  description: z.string(),
});

export const ConsistencyReviewSchema = z.object({
  violations: z.array(z.object({
    component: z.string(),
    violation_type: z.string(),
    severity: z.enum(['info', 'warning', 'error']),
    suggestion: z.string(),
  })),
  suggestions: z.array(z.string()),
  consistency_score: z.number().min(0).max(100),
});

export const AccessibilityCheckSchema = z.object({
  wcag_level: z.enum(['A', 'AA', 'AAA']),
  checklist_items: z.array(z.object({
    criterion: z.string(),
    status: z.enum(['pass', 'fail', 'na']),
    note: z.string().optional(),
  })),
  violations: z.array(z.string()),
});

export type GenerateWireframeInput = z.infer<typeof GenerateWireframeSchema>;
export type CreateDesignTokensInput = z.infer<typeof CreateDesignTokensSchema>;
export type SuggestUiComponentsInput = z.infer<typeof SuggestUiComponentsSchema>;
export type GenerateUxWritingInput = z.infer<typeof GenerateUxWritingSchema>;
export type MapVisualStatesInput = z.infer<typeof MapVisualStatesSchema>;
export type ReviewUiConsistencyInput = z.infer<typeof ReviewUiConsistencySchema>;
export type ValidateVisualAccessibilityInput = z.infer<typeof ValidateVisualAccessibilitySchema>;
export type Wireframe = z.infer<typeof WireframeSchema>;
export type DesignTokens = z.infer<typeof DesignTokensSchema>;
export type ComponentSuggestion = z.infer<typeof ComponentSuggestionSchema>;
export type UxWriting = z.infer<typeof UxWritingSchema>;
export type VisualState = z.infer<typeof VisualStateSchema>;
export type ConsistencyReview = z.infer<typeof ConsistencyReviewSchema>;
export type AccessibilityCheck = z.infer<typeof AccessibilityCheckSchema>;
