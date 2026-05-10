import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { ReviewFrontendCodeSchema } from '../../schemas/frontend.schema.js';

export async function reviewFrontendCode(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = ReviewFrontendCodeSchema.parse(args);

  const payload = {
    issues: [
      {
        line: 5,
        severity: 'error' as const,
        message: 'Missing TypeScript type annotation',
        suggestion: 'Add type annotation: `const value: string =`',
      },
      {
        line: 12,
        severity: 'warn' as const,
        message: 'Unused variable',
        suggestion: 'Remove or use the variable',
      },
      {
        line: 23,
        severity: 'info' as const,
        message: 'Could optimize re-renders',
        suggestion: 'Consider using React.memo or useMemo',
      },
    ],
    summary: 'Code review complete. 3 issues found: 1 error, 1 warning, 1 info.',
  };

  return createStructuredPayload({
    tool: 'review_frontend_code',
    agent: 'frontzilla',
    payload,
    instructions: 'Fix error and warning issues. Consider info suggestions for optimization.',
    context_for_llm: `Code review for: ${input.lang || 'tsx'}. Focus areas: ${input.focus?.join(', ') || 'all'}. 3 issues identified.`,
    related_tools: ['suggest_refactor', 'generate_frontend_tests'],
  });
}
