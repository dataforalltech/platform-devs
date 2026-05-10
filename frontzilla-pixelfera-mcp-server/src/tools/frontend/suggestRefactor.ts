import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { SuggestRefactorSchema } from '../../schemas/frontend.schema.js';

export async function suggestRefactor(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = SuggestRefactorSchema.parse(args);

  const payload = {
    motivation: input.goal || 'Improve code readability and maintainability',
    steps: [
      {
        step_number: 1,
        description: 'Extract repeated logic into helper function',
        code_before: 'const x = y + z; const a = b + c;',
        code_after: 'const helper = (a, b) => a + b; const x = helper(y, z);',
      },
      {
        step_number: 2,
        description: 'Use TypeScript type utilities',
        code_before: 'type A = { x: string }; type B = { x: string, y: number };',
        code_after: 'type A = { x: string }; type B = A & { y: number };',
      },
    ],
    new_code: 'Refactored code placeholder',
    benefits: [
      'Reduced duplication (DRY principle)',
      'Improved type safety',
      'Better testability',
      'Easier maintenance',
    ],
  };

  return createStructuredPayload({
    tool: 'suggest_refactor',
    agent: 'frontzilla',
    payload,
    instructions: 'Review refactor plan. Apply changes incrementally. Test after each step.',
    context_for_llm: `Refactor suggestion. Goal: ${input.goal || 'general improvement'}. ${payload.steps.length} refactor steps. Benefits: ${payload.benefits.join(', ')}.`,
    related_tools: ['review_frontend_code', 'generate_frontend_tests'],
  });
}
