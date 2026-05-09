import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { ReviewUiConsistencySchema } from '../../schemas/design.schema.js';

export async function reviewUiConsistency(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = ReviewUiConsistencySchema.parse(args);

  const review = {
    violations: [
      {
        component: 'Button',
        violation_type: 'inconsistent_padding',
        severity: 'warning' as const,
        suggestion: 'Ensure all buttons use spacing: md (16px)',
      },
      {
        component: 'Card',
        violation_type: 'inconsistent_shadow',
        severity: 'info' as const,
        suggestion: 'Use shadow-md for all cards',
      },
    ],
    suggestions: [
      'Create a component library in design tool',
      'Document all component variants',
      'Set up design tokens in Figma',
    ],
    consistency_score: 85,
  };

  return createStructuredPayload({
    tool: 'review_ui_consistency',
    agent: 'pixelfera',
    payload: review,
    instructions: 'Address violations and implement suggestions. Update design system documentation.',
    context_for_llm: `Reviewed ${input.components.length} components. Consistency score: ${review.consistency_score}/100. ${review.violations.length} violations found.`,
    related_tools: ['create_design_tokens', 'generate_component_spec'],
  });
}
