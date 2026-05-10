import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { SplitTasksSchema } from '../../schemas/requirement.schema.js';

export async function splitDesignAndFrontendTasks(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = SplitTasksSchema.parse(args);

  const feature = store.getFeature(input.feature_id);
  if (!feature) {
    return { error: 'feature_not_found', feature_id: input.feature_id };
  }

  const analysis = feature.analysis as Record<string, unknown>;
  const screens = (analysis.screens as string[]) || [];
  const flows = (analysis.flows as string[]) || [];

  const pixelferaTasks = [
    '1. Create wireframes for all screens',
    '2. Define design tokens (colors, typography, spacing)',
    '3. Design visual states (hover, focus, disabled, loading)',
    '4. Create component library in design tool',
    '5. Document design patterns and guidelines',
  ];

  const frontzillaTasks = [
    '1. Review wireframes and provide implementation feedback',
    '2. Create component structure and TypeScript types',
    '3. Implement components with responsive design',
    '4. Set up API services and state management',
    '5. Write tests and handle edge cases',
  ];

  if (screens.length > 0) {
    pixelferaTasks.push(`6. Design screens: ${screens.join(', ')}`);
    frontzillaTasks.push(`6. Implement screens: ${screens.join(', ')}`);
  }

  const tasksData = {
    feature_id: feature.id,
    pixelfera_tasks: pixelferaTasks,
    frontzilla_tasks: frontzillaTasks,
    collaboration_points: [
      'Wireframe review and feedback',
      'Design token implementation',
      'Component handoff checklist',
      'Testing and QA',
    ],
  };

  return createStructuredPayload({
    tool: 'split_design_and_frontend_tasks',
    agent: 'orchestrator',
    payload: tasksData,
    instructions:
      'Share pixelfera_tasks with PixelFera agent and frontzilla_tasks with FrontZilla agent. Use collaboration_points to sync work.',
    context_for_llm: `Feature: ${feature.name}. Screens: ${screens.join(', ')}. PixelFera handles: design tokens, wireframes, component specs. FrontZilla implements: React/Next.js components, APIs, tests.`,
    feature_id: feature.id,
    related_tools: [
      'generate_wireframe',
      'create_design_tokens',
      'generate_react_component',
      'generate_nextjs_page',
    ],
  });
}
