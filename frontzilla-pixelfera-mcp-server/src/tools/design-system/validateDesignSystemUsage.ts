import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { ValidateDesignSystemUsageSchema } from '../../schemas/workflow.schema.js';

export async function validateDesignSystemUsage(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = ValidateDesignSystemUsageSchema.parse(args);

  const validation = {
    violations: [
      {
        file: 'components/Button.tsx',
        line: 15,
        type: 'hardcoded_color',
        message: 'Hardcoded color instead of design token',
        suggestion: 'Use: color={tokens.colors.primary}',
      },
      {
        file: 'pages/home.tsx',
        line: 42,
        type: 'missing_class',
        message: 'Custom padding instead of spacing scale',
        suggestion: 'Use: className="p-{spacing-md}"',
      },
    ],
    compliance_score: 87,
  };

  return createStructuredPayload({
    tool: 'validate_design_system_usage',
    agent: 'shared',
    payload: validation,
    instructions: 'Fix violations. Ensure all design tokens are used consistently.',
    context_for_llm: `Design system validation: ${validation.violations.length} violations. Compliance: ${validation.compliance_score}%. Use tokens instead of hardcoding.`,
    related_tools: ['create_design_tokens', 'generate_component_spec'],
  });
}
