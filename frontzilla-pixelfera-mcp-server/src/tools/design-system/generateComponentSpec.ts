import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { DesignSystemComponentSpecSchema } from '../../schemas/workflow.schema.js';

export async function generateComponentSpec(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = DesignSystemComponentSpecSchema.parse(args);

  const spec = {
    name: input.name,
    category: input.category,
    props: [
      {
        name: 'variant',
        type: 'string',
        required: false,
        description: 'Visual variant of component',
      },
      {
        name: 'size',
        type: 'sm | md | lg',
        required: false,
        description: 'Component size',
      },
      {
        name: 'disabled',
        type: 'boolean',
        required: false,
        description: 'Disabled state',
      },
    ],
    variants: [
      { name: 'default', description: 'Default appearance' },
      { name: 'primary', description: 'Primary action variant' },
      { name: 'secondary', description: 'Secondary action variant' },
    ],
    states: ['default', 'hover', 'active', 'focus', 'disabled', 'loading'],
    tokens_used: ['color-primary', 'spacing-md', 'radius-md'],
    usage_example: `<${input.name} variant="primary" size="lg" />`,
  };

  let component: any;
  if (input.feature_id) {
    component = store.createComponent(
      input.name,
      input.category,
      'shared',
      spec,
      input.feature_id
    );
  }

  return createStructuredPayload({
    tool: 'generate_component_spec',
    agent: 'shared',
    payload: spec,
    instructions: 'Document component in design system. Create variants in design tool. Export to code.',
    context_for_llm: `Component spec: ${input.name} (${input.category}). ${spec.props.length} props. ${spec.variants.length} variants. ${spec.states.length} states.`,
    feature_id: input.feature_id,
    component_id: component?.id,
    related_tools: [
      'generate_component_variants',
      'document_component',
      'generate_storybook_story',
    ],
  });
}
