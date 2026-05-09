import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateFeatureSpecSchema } from '../../schemas/requirement.schema.js';

export async function generateFeatureSpec(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateFeatureSpecSchema.parse(args);

  const feature = store.getFeature(input.feature_id);
  if (!feature) {
    return { error: 'feature_not_found', feature_id: input.feature_id };
  }

  const analysis = feature.analysis as Record<string, unknown>;
  const screens = ((analysis.screens as string[]) || []).slice(0, 3);
  const flows = ((analysis.flows as string[]) || []).slice(0, 3);

  const spec = {
    wireframe_hints: screens.map((screen) => `${screen} - wireframe required`),
    api_contracts: flows.map((flow, idx) => ({
      endpoint: `/api/${flow.toLowerCase().replace(/\s+/g, '-')}`,
      method: idx % 3 === 0 ? 'GET' : idx % 3 === 1 ? 'POST' : 'PUT',
      request_schema: { type: 'object', properties: {} },
      response_schema: { type: 'object', properties: { success: { type: 'boolean' } } },
    })),
    component_list: [
      'Layout',
      'Header',
      'Navigation',
      'Card',
      'Button',
      'Form',
      'Input',
      'Modal',
    ],
    design_system_requirements: {
      color_palette: ['primary', 'secondary', 'neutral'],
      typography: ['heading-1', 'heading-2', 'body', 'caption'],
      spacing: ['4px', '8px', '16px', '24px', '32px'],
    },
  };

  store.updateFeatureStatus(feature.id, 'analysis', spec);

  return createStructuredPayload({
    tool: 'generate_feature_spec',
    agent: 'shared',
    payload: {
      feature_id: feature.id,
      spec,
      detail_level: input.detail_level || 'standard',
    },
    instructions:
      'Use this spec as blueprint for design and development. Share with both PixelFera and FrontZilla.',
    context_for_llm: `Feature spec includes ${screens.length} screens, ${flows.length} flows, ${spec.component_list.length} components. Detail level: ${input.detail_level || 'standard'}.`,
    feature_id: feature.id,
    related_tools: [
      'generate_screen_brief',
      'generate_wireframe',
      'generate_react_component',
    ],
  });
}
