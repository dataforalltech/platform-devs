import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { RunUiFeatureWorkflowSchema } from '../../schemas/workflow.schema.js';

export async function runUiFeatureWorkflow(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = RunUiFeatureWorkflowSchema.parse(args);

  const target = input.target || 'complete';
  const stack = input.stack || 'nextjs';

  const analysis = {
    screens: ['Dashboard', 'Settings', 'Profile'],
    flows: ['User login', 'Create item', 'Edit item', 'Delete item'],
    actors: ['user', 'admin'],
    complexity: 'medium',
    estimated_effort_hours: 8,
  };

  const feature = store.createFeature(
    `UI Feature - ${input.requirement.substring(0, 50)}`,
    input.requirement,
    analysis
  );

  const workflow = store.createWorkflow(feature.id);

  const result = {
    feature_id: feature.id,
    workflow_id: workflow.id,
    target,
    stack,
    analysis: target === 'analysis' || target === 'complete' ? analysis : undefined,
    design_tasks:
      target === 'design' || target === 'complete'
        ? [
            'Generate wireframes for 3 screens',
            'Create design tokens (colors, typography, spacing)',
            'Design visual states (hover, focus, disabled)',
            'Create component library specs',
            'Document design patterns',
          ]
        : undefined,
    frontend_tasks:
      target === 'frontend' || target === 'complete'
        ? [
            'Set up Next.js project structure',
            'Create component architecture',
            'Implement pages and routes',
            'Set up API services and types',
            'Implement forms with validation',
            'Add tests and error handling',
          ]
        : undefined,
    collaboration_points: [
      'Design handoff meeting',
      'Wireframe review and feedback',
      'Component spec review',
      'Testing and QA alignment',
    ],
  };

  store.completeWorkflow(workflow.id, 'completed', result);

  return {
    ...createStructuredPayload({
      tool: 'run_ui_feature_workflow',
      agent: 'orchestrator',
      payload: result,
      instructions: `Execute workflow targeting: ${target}. Share analysis with both agents. Coordinate via collaboration_points.`,
      context_for_llm: `Full UI feature workflow initiated. Feature: ${feature.name}. Target: ${target}. Stack: ${stack}. 3 screens, 4 flows identified.`,
      feature_id: feature.id,
      related_tools: [
        'analyze_requirement',
        'split_design_and_frontend_tasks',
        'generate_feature_spec',
      ],
    }),
  };
}
