import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { DocumentComponentSchema } from '../../schemas/workflow.schema.js';

export async function documentComponent(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = DocumentComponentSchema.parse(args);

  const component = store.getComponent(input.component_id);
  if (!component) {
    return { error: 'component_not_found', component_id: input.component_id };
  }

  const markdown = `# ${component.name}

## Description
A reusable component for displaying [purpose].

## Props
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| variant | string | No | default | Visual variant |
| size | string | No | md | Component size |
| disabled | boolean | No | false | Disabled state |

## Usage
\`\`\`tsx
import { ${component.name} } from '@components';

export function Example() {
  return <${component.name} variant="primary" size="lg" />;
}
\`\`\`

## Do's ✓
- Use for primary actions
- Pair with meaningful labels
- Ensure sufficient contrast

## Don'ts ✗
- Don't use for tertiary actions
- Don't use without labels
- Don't disable without reason
`;

  const documentation = {
    markdown,
    props_table: [
      { name: 'variant', type: 'string', required: false, default: 'default', description: 'Visual variant' },
      { name: 'size', type: 'sm | md | lg', required: false, default: 'md', description: 'Component size' },
      { name: 'disabled', type: 'boolean', required: false, default: false, description: 'Disabled state' },
    ],
    examples: [
      { label: 'Primary button', code: '<Button variant="primary">Click me</Button>' },
      { label: 'Disabled state', code: '<Button disabled>Disabled</Button>' },
    ],
    do_dont: {
      do: ['Use for actions', 'Add labels', 'Test accessibility'],
      dont: ['Use for links', 'Omit labels', 'Use disabled without reason'],
    },
  };

  store.updateComponent(input.component_id, { doc: markdown });

  return createStructuredPayload({
    tool: 'document_component',
    agent: 'pixelfera',
    payload: documentation,
    instructions: 'Finalize documentation. Add to design system wiki. Share with team.',
    context_for_llm: `Documentation for component: ${component.name}. Markdown format with usage examples, do/dont.`,
    component_id: input.component_id,
    related_tools: ['generate_storybook_story', 'validate_design_system_usage'],
  });
}
