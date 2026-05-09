import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateComponentVariantsSchema } from '../../schemas/workflow.schema.js';

export async function generateComponentVariants(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateComponentVariantsSchema.parse(args);

  const component = store.getComponent(input.component_id);
  if (!component) {
    return { error: 'component_not_found', component_id: input.component_id };
  }

  const payload = {
    component_name: component.name,
    variants: [
      { name: 'small', size: 'sm', color: 'primary', intent: 'default', shape: 'rounded' },
      { name: 'medium', size: 'md', color: 'primary', intent: 'default', shape: 'rounded' },
      { name: 'large', size: 'lg', color: 'primary', intent: 'default', shape: 'rounded' },
      { name: 'secondary', size: 'md', color: 'secondary', intent: 'secondary', shape: 'rounded' },
      { name: 'destructive', size: 'md', color: 'destructive', intent: 'destructive', shape: 'rounded' },
    ],
  };

  return createStructuredPayload({
    tool: 'generate_component_variants',
    agent: 'pixelfera',
    payload,
    instructions: 'Create variant components in design tool. Export specs for each variant.',
    context_for_llm: `Variants for component: ${component.name}. ${payload.variants.length} variants: ${payload.variants.map((v) => v.name).join(', ')}.`,
    component_id: input.component_id,
    related_tools: ['document_component', 'generate_storybook_story'],
  });
}
