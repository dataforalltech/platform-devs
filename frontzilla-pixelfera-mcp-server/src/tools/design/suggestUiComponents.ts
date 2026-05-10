import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { SuggestUiComponentsSchema } from '../../schemas/design.schema.js';

export async function suggestUiComponents(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = SuggestUiComponentsSchema.parse(args);

  const suggestions = [
    {
      name: 'Button',
      category: 'atom',
      props: [
        { name: 'variant', type: 'primary | secondary | ghost', required: true, default: 'primary' },
        { name: 'size', type: 'sm | md | lg', required: false, default: 'md' },
        { name: 'disabled', type: 'boolean', required: false, default: false },
      ],
    },
    {
      name: 'Input',
      category: 'atom',
      props: [
        { name: 'type', type: 'text | email | password', required: false, default: 'text' },
        { name: 'placeholder', type: 'string', required: false },
        { name: 'error', type: 'string', required: false },
      ],
    },
    {
      name: 'Card',
      category: 'molecule',
      props: [
        { name: 'title', type: 'string', required: false },
        { name: 'subtitle', type: 'string', required: false },
        { name: 'padding', type: 'sm | md | lg', required: false, default: 'md' },
      ],
    },
    {
      name: 'List',
      category: 'organism',
      props: [
        { name: 'items', type: 'Array<T>', required: true },
        { name: 'renderItem', type: 'function', required: true },
        { name: 'onSelectItem', type: 'function', required: false },
      ],
    },
  ];

  return createStructuredPayload({
    tool: 'suggest_ui_components',
    agent: 'pixelfera',
    payload: {
      screen_name: input.screen_name,
      suggestions,
      total_components: suggestions.length,
    },
    instructions: 'Review suggestions and customize for your design system. Share with FrontZilla for implementation.',
    context_for_llm: `For screen: ${input.screen_name}. Suggested ${suggestions.length} components. Key atoms: Button, Input. Key molecules: Card. Key organisms: List.`,
    feature_id: input.feature_id,
    related_tools: ['generate_component_spec', 'generate_react_component'],
  });
}
