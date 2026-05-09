import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateStorybookStorySchema } from '../../schemas/workflow.schema.js';

export async function generateStorybookStory(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateStorybookStorySchema.parse(args);

  const typescriptCode = `import type { Meta, StoryObj } from '@storybook/react';
import { ${input.component_name} } from './${input.component_name}.js';

const meta = {
  title: 'Components/${input.component_name}',
  component: ${input.component_name},
  parameters: {
    layout: 'centered',
  },
  tags: ['autodocs'],
} satisfies Meta<typeof ${input.component_name}>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {},
};

export const Primary: Story = {
  args: {
    variant: 'primary',
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

export const Large: Story = {
  args: {
    size: 'lg',
  },
};
`;

  const payload = {
    filename: `${input.component_name}.stories.ts`,
    typescript_code: typescriptCode,
    stories: [
      { name: 'Default', args: {} },
      { name: 'Primary', args: { variant: 'primary' } },
      { name: 'Disabled', args: { disabled: true } },
      { name: 'Large', args: { size: 'lg' } },
    ],
  };

  if (input.component_id) {
    const component = store.getComponent(input.component_id);
    if (component) {
      store.updateComponent(input.component_id, { story: typescriptCode });
    }
  }

  return createStructuredPayload({
    tool: 'generate_storybook_story',
    agent: 'shared',
    payload,
    instructions: 'Add story file to Storybook. Create interactive controls for props.',
    context_for_llm: `Storybook story for component: ${input.component_name}. CSF 3.0 format. ${payload.stories.length} stories.`,
    component_id: input.component_id,
    related_tools: ['document_component', 'generate_react_component'],
  });
}
