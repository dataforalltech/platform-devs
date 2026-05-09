import { z } from 'zod';

export const RunUiFeatureWorkflowSchema = z.object({
  requirement: z.string().min(10),
  context: z.string().optional(),
  target: z.enum(['analysis', 'design', 'frontend', 'complete']).optional(),
  stack: z.enum(['react', 'nextjs', 'vue', 'svelte']).optional(),
});

export const DesignSystemComponentSpecSchema = z.object({
  name: z.string().min(3),
  category: z.enum(['atom', 'molecule', 'organism', 'template', 'page']),
  feature_id: z.string().optional(),
});

export const GenerateComponentVariantsSchema = z.object({
  component_id: z.string().startsWith('comp_'),
});

export const DocumentComponentSchema = z.object({
  component_id: z.string().startsWith('comp_'),
});

export const ValidateDesignSystemUsageSchema = z.object({
  code: z.string(),
  design_system: z.record(z.unknown()).optional(),
});

export const GenerateStorybookStorySchema = z.object({
  component_name: z.string().min(3),
  component_id: z.string().optional(),
});

export const WorkflowResultSchema = z.object({
  feature_id: z.string().startsWith('feat_'),
  analysis: z.object({
    screens: z.array(z.string()),
    flows: z.array(z.string()),
    actors: z.array(z.string()),
    complexity: z.enum(['low', 'medium', 'high']),
    estimated_hours: z.number(),
  }).optional(),
  design_output: z.object({
    wireframes: z.array(z.object({
      name: z.string(),
      ascii: z.string(),
    })),
    design_tokens: z.record(z.unknown()),
    component_suggestions: z.array(z.string()),
  }).optional(),
  frontend_output: z.object({
    components: z.array(z.object({
      name: z.string(),
      filename: z.string(),
      code: z.string(),
    })),
    pages: z.array(z.object({
      route: z.string(),
      filename: z.string(),
      code: z.string(),
    })),
    hooks: z.array(z.object({
      name: z.string(),
      filename: z.string(),
      code: z.string(),
    })),
    services: z.array(z.object({
      name: z.string(),
      filename: z.string(),
      code: z.string(),
    })),
  }).optional(),
  pixelfera_next_steps: z.array(z.string()).optional(),
  frontzilla_next_steps: z.array(z.string()).optional(),
  integration_notes: z.string().optional(),
});

export const ComponentSpecSchema = z.object({
  name: z.string(),
  category: z.enum(['atom', 'molecule', 'organism', 'template', 'page']),
  props: z.array(z.object({
    name: z.string(),
    type: z.string(),
    required: z.boolean(),
    description: z.string().optional(),
  })),
  variants: z.array(z.object({
    name: z.string(),
    description: z.string(),
  })).optional(),
  states: z.array(z.string()),
  tokens_used: z.array(z.string()).optional(),
  usage_example: z.string().optional(),
});

export const ComponentVariantsSchema = z.object({
  component_name: z.string(),
  variants: z.array(z.object({
    name: z.string(),
    size: z.string().optional(),
    color: z.string().optional(),
    intent: z.string().optional(),
    shape: z.string().optional(),
    props_override: z.record(z.unknown()).optional(),
  })),
});

export const ComponentDocumentationSchema = z.object({
  markdown: z.string(),
  props_table: z.array(z.object({
    name: z.string(),
    type: z.string(),
    required: z.boolean(),
    default: z.unknown().optional(),
    description: z.string(),
  })),
  examples: z.array(z.object({
    label: z.string(),
    code: z.string(),
  })),
  do_dont: z.object({
    do: z.array(z.string()),
    dont: z.array(z.string()),
  }).optional(),
});

export const DesignSystemUsageValidationSchema = z.object({
  violations: z.array(z.object({
    file: z.string(),
    line: z.number(),
    type: z.string(),
    message: z.string(),
    suggestion: z.string(),
  })),
  compliance_score: z.number().min(0).max(100),
});

export const StorybookStorySchema = z.object({
  filename: z.string(),
  typescript_code: z.string(),
  stories: z.array(z.object({
    name: z.string(),
    args: z.record(z.unknown()),
  })),
});

export type RunUiFeatureWorkflowInput = z.infer<typeof RunUiFeatureWorkflowSchema>;
export type DesignSystemComponentSpecInput = z.infer<typeof DesignSystemComponentSpecSchema>;
export type GenerateComponentVariantsInput = z.infer<typeof GenerateComponentVariantsSchema>;
export type DocumentComponentInput = z.infer<typeof DocumentComponentSchema>;
export type ValidateDesignSystemUsageInput = z.infer<typeof ValidateDesignSystemUsageSchema>;
export type GenerateStorybookStoryInput = z.infer<typeof GenerateStorybookStorySchema>;
export type WorkflowResult = z.infer<typeof WorkflowResultSchema>;
export type ComponentSpec = z.infer<typeof ComponentSpecSchema>;
export type ComponentVariants = z.infer<typeof ComponentVariantsSchema>;
export type ComponentDocumentation = z.infer<typeof ComponentDocumentationSchema>;
export type DesignSystemUsageValidation = z.infer<typeof DesignSystemUsageValidationSchema>;
export type StorybookStory = z.infer<typeof StorybookStorySchema>;
