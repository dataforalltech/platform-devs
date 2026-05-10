import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { MapVisualStatesSchema } from '../../schemas/design.schema.js';

export async function mapVisualStates(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = MapVisualStatesSchema.parse(args);

  const states = [
    {
      name: 'default',
      properties: { background: '#ffffff', color: '#1f2937', opacity: 1 },
      description: 'Normal state',
    },
    {
      name: 'hover',
      properties: { background: '#f3f4f6', color: '#1f2937', opacity: 1 },
      description: 'User hovers over element',
    },
    {
      name: 'focus',
      properties: { outline: '2px solid #2563eb', outlineOffset: '2px' },
      description: 'Element has keyboard focus',
    },
    {
      name: 'active',
      properties: { background: '#e5e7eb', color: '#1f2937' },
      description: 'Element is active/pressed',
    },
    {
      name: 'disabled',
      properties: { opacity: 0.5, cursor: 'not-allowed' },
      description: 'Element is disabled',
    },
    {
      name: 'loading',
      properties: { opacity: 0.7, animation: 'pulse 2s infinite' },
      description: 'Element is loading',
    },
    {
      name: 'error',
      properties: { background: '#fee2e2', color: '#991b1b', border: '1px solid #dc2626' },
      description: 'Error state',
    },
    {
      name: 'success',
      properties: { background: '#dcfce7', color: '#166534', border: '1px solid #22c55e' },
      description: 'Success state',
    },
  ];

  return createStructuredPayload({
    tool: 'map_visual_states',
    agent: 'pixelfera',
    payload: {
      component_name: input.component_name,
      states,
    },
    instructions: 'Use these states in your design tool. Create variants for each state. Export to FrontZilla.',
    context_for_llm: `Visual states for component: ${input.component_name}. Total states: ${states.length}. Includes: default, hover, focus, active, disabled, loading, error, success.`,
    feature_id: input.feature_id,
    related_tools: ['generate_component_spec', 'generate_react_component'],
  });
}
