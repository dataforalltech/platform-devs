import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateScreenBriefSchema } from '../../schemas/requirement.schema.js';

export async function generateScreenBrief(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateScreenBriefSchema.parse(args);

  const feature = store.getFeature(input.feature_id);
  if (!feature) {
    return { error: 'feature_not_found', feature_id: input.feature_id };
  }

  const brief = {
    layout: 'main-sidebar | main-content',
    states: [
      { name: 'empty', description: 'No data to display' },
      { name: 'loading', description: 'Data is being fetched' },
      { name: 'default', description: 'Normal state with data' },
      { name: 'error', description: 'Error occurred during data fetch' },
      { name: 'success', description: 'Action completed successfully' },
    ],
    interactions: [
      {
        trigger: 'user clicks "Create"',
        action: 'Open dialog modal',
        result: 'User can fill form',
      },
      {
        trigger: 'user submits form',
        action: 'Validate and send API request',
        result: 'Item is created or error shown',
      },
      {
        trigger: 'user clicks item',
        action: 'Navigate to detail view',
        result: 'Display item details',
      },
    ],
    data_bindings: [
      { element: 'List', source: 'GET /api/items' },
      { element: 'Title', source: 'item.name' },
      { element: 'Description', source: 'item.description' },
    ],
  };

  return createStructuredPayload({
    tool: 'generate_screen_brief',
    agent: 'shared',
    payload: {
      feature_id: feature.id,
      screen_name: input.screen_name,
      brief,
    },
    instructions: 'Use this brief for wireframing (PixelFera) and component design (FrontZilla).',
    context_for_llm: `Screen: ${input.screen_name}. Has ${brief.states.length} states and ${brief.interactions.length} interactions. Key data: ${brief.data_bindings.map((b) => b.element).join(', ')}.`,
    feature_id: feature.id,
    related_tools: ['generate_wireframe', 'generate_react_component', 'map_visual_states'],
  });
}
