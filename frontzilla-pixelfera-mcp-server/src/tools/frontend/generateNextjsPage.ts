import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateNextjsPageSchema } from '../../schemas/frontend.schema.js';

export async function generateNextjsPage(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateNextjsPageSchema.parse(args);
  const pageType = input.type || 'app-route';

  const typescriptCode = `import { Suspense } from 'react';
import { Metadata } from 'next';

export const metadata: Metadata = {
  title: '${input.route}',
  description: 'Page for ${input.route}',
};

async function PageContent() {
  // Fetch data here
  return <div>Page content for ${input.route}</div>;
}

function PageSkeleton() {
  return <div>Loading...</div>;
}

export default function Page() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PageContent />
    </Suspense>
  );
}
`;

  const payload = {
    filename: `page.tsx`,
    route_segment: input.route,
    typescript_code: typescriptCode,
    metadata: {
      title: `${input.route} - App`,
      description: `Page for ${input.route}`,
    },
    features: ['async-components', 'suspense'],
  };

  return createStructuredPayload({
    tool: 'generate_nextjs_page',
    agent: 'frontzilla',
    payload,
    instructions: 'Add page-specific logic, data fetching, and layouts as needed.',
    context_for_llm: `Next.js page scaffold for route: ${input.route}. Type: ${pageType}. Features: async/Suspense.`,
    feature_id: input.feature_id,
    related_tools: ['generate_react_component', 'generate_api_service'],
  });
}
