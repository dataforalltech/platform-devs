import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateFrontendTestsSchema } from '../../schemas/frontend.schema.js';

export async function generateFrontendTests(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateFrontendTestsSchema.parse(args);

  const unitTests = `import { render, screen } from '@testing-library/react';
import { ${input.component_name} } from './${input.component_name}.js';

describe('${input.component_name}', () => {
  it('renders without crashing', () => {
    render(<${input.component_name} />);
    expect(screen.getByText(/component/i)).toBeInTheDocument();
  });

  it('handles interactions correctly', () => {
    render(<${input.component_name} />);
    // Add interaction tests
  });

  it('displays loading state', () => {
    render(<${input.component_name} isLoading={true} />);
    // Assert loading state
  });

  it('displays error state', () => {
    render(<${input.component_name} error="Test error" />);
    // Assert error state
  });
});
`;

  const e2eTests = `import { test, expect } from '@playwright/test';

test('${input.component_name} workflow', async ({ page }) => {
  await page.goto('/');
  // Add e2e test steps
  await expect(page).toHaveTitle(/title/);
});
`;

  const payload = {
    unit_tests: unitTests,
    e2e_tests: e2eTests,
    test_coverage: [
      { scenario: 'Component renders', assert: 'Element is in document' },
      { scenario: 'User interaction', assert: 'State updates correctly' },
      { scenario: 'Error handling', assert: 'Error message displays' },
    ],
  };

  return createStructuredPayload({
    tool: 'generate_frontend_tests',
    agent: 'frontzilla',
    payload,
    instructions: 'Expand test cases to cover all component scenarios. Achieve >80% coverage.',
    context_for_llm: `Tests for component: ${input.component_name}. Type: ${input.test_type || 'all'}. Includes unit and E2E tests.`,
    related_tools: ['generate_react_component', 'review_frontend_code'],
  });
}
