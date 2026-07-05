import { z } from 'zod';
import { StyleFrameworkSchema, FrontendLibrarySchema, TestTypeSchema } from '../utils/validators.js';

export const GenerateReactComponentSchema = z.object({
  name: z.string().min(3),
  props: z.array(z.object({
    name: z.string(),
    type: z.string(),
    required: z.boolean(),
    default: z.unknown().optional(),
  })).optional(),
  variant: z.string().optional(),
  styling: StyleFrameworkSchema.optional(),
});

export const GenerateNextjsPageSchema = z.object({
  route: z.string(),
  feature_id: z.string().optional(),
  type: z.enum(['app-route', 'layout', 'error', 'loading']).optional(),
});

export const GenerateTypescriptTypesSchema = z.object({
  entity_name: z.string().min(3),
  fields: z.array(z.object({
    name: z.string(),
    type: z.string(),
    required: z.boolean(),
    description: z.string().optional(),
  })).optional(),
  pattern: z.enum(['interface', 'type', 'enum']).optional(),
});

export const GenerateApiServiceSchema = z.object({
  entity: z.string().min(3),
  endpoints: z.array(z.object({
    path: z.string(),
    method: z.enum(['GET', 'POST', 'PUT', 'DELETE', 'PATCH']),
  })).optional(),
  base_url: z.string().optional(),
});

export const GenerateCustomHookSchema = z.object({
  name: z.string().regex(/^use[A-Z]/),
  purpose: z.string(),
  dependencies: z.array(z.string()).optional(),
});

export const GenerateFormWithValidationSchema = z.object({
  form_name: z.string().min(3),
  fields: z.array(z.object({
    name: z.string(),
    type: z.string(),
    label: z.string(),
    required: z.boolean(),
    validation: z.string().optional(),
  })),
  library: FrontendLibrarySchema.optional(),
});

export const GenerateFrontendTestsSchema = z.object({
  component_name: z.string().min(3),
  test_type: TestTypeSchema.optional(),
});

export const ReviewFrontendCodeSchema = z.object({
  code: z.string(),
  lang: z.enum(['typescript', 'jsx', 'tsx']).optional(),
  focus: z.array(z.enum(['performance', 'accessibility', 'security', 'types', 'patterns'])).optional(),
});

export const SuggestRefactorSchema = z.object({
  code: z.string(),
  goal: z.string().optional(),
});

export const ReactComponentSchema = z.object({
  filename: z.string(),
  typescript_code: z.string(),
  exports: z.array(z.string()),
  props_interface: z.string(),
  imports: z.array(z.string()),
});

export const NextjsPageSchema = z.object({
  filename: z.string(),
  route_segment: z.string(),
  typescript_code: z.string(),
  metadata: z.object({
    title: z.string(),
    description: z.string(),
  }).optional(),
  features: z.array(z.enum(['async-components', 'suspense', 'error-boundary', 'layout'])),
});

export const TypescriptTypesSchema = z.object({
  code: z.string(),
  type_name: z.string(),
  zod_schema: z.string().optional(),
});

export const ApiServiceSchema = z.object({
  filename: z.string(),
  typescript_code: z.string(),
  base_url: z.string(),
  endpoints: z.record(z.object({
    method: z.string(),
    path: z.string(),
    request_type: z.string(),
    response_type: z.string(),
  })),
});

export const CustomHookSchema = z.object({
  filename: z.string(),
  typescript_code: z.string(),
  hook_name: z.string(),
  return_type: z.string(),
});

export const FormWithValidationSchema = z.object({
  filename: z.string(),
  typescript_code: z.string(),
  form_name: z.string(),
  validation_schema: z.string(),
});

export const FrontendTestsSchema = z.object({
  unit_tests: z.string().optional(),
  e2e_tests: z.string().optional(),
  test_coverage: z.array(z.object({
    scenario: z.string(),
    assert: z.string(),
  })),
});

export const CodeReviewSchema = z.object({
  issues: z.array(z.object({
    line: z.number(),
    severity: z.enum(['error', 'warn', 'info']),
    message: z.string(),
    suggestion: z.string().optional(),
  })),
  summary: z.string(),
});

export const RefactorPlanSchema = z.object({
  motivation: z.string(),
  steps: z.array(z.object({
    step_number: z.number(),
    description: z.string(),
    code_before: z.string().optional(),
    code_after: z.string().optional(),
  })),
  new_code: z.string(),
  benefits: z.array(z.string()),
});

export type GenerateReactComponentInput = z.infer<typeof GenerateReactComponentSchema>;
export type GenerateNextjsPageInput = z.infer<typeof GenerateNextjsPageSchema>;
export type GenerateTypescriptTypesInput = z.infer<typeof GenerateTypescriptTypesSchema>;
export type GenerateApiServiceInput = z.infer<typeof GenerateApiServiceSchema>;
export type GenerateCustomHookInput = z.infer<typeof GenerateCustomHookSchema>;
export type GenerateFormWithValidationInput = z.infer<typeof GenerateFormWithValidationSchema>;
export type GenerateFrontendTestsInput = z.infer<typeof GenerateFrontendTestsSchema>;
export type ReviewFrontendCodeInput = z.infer<typeof ReviewFrontendCodeSchema>;
export type SuggestRefactorInput = z.infer<typeof SuggestRefactorSchema>;
export type ReactComponent = z.infer<typeof ReactComponentSchema>;
export type NextjsPage = z.infer<typeof NextjsPageSchema>;
export type TypescriptTypes = z.infer<typeof TypescriptTypesSchema>;
export type ApiService = z.infer<typeof ApiServiceSchema>;
export type CustomHook = z.infer<typeof CustomHookSchema>;
export type FormWithValidation = z.infer<typeof FormWithValidationSchema>;
export type FrontendTests = z.infer<typeof FrontendTestsSchema>;
export type CodeReview = z.infer<typeof CodeReviewSchema>;
export type RefactorPlan = z.infer<typeof RefactorPlanSchema>;
