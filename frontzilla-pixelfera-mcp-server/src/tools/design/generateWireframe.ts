import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateWireframeSchema } from '../../schemas/design.schema.js';

export async function generateWireframe(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateWireframeSchema.parse(args);

  const layout = input.layout || 'single-column';
  const wireframeAscii = generateAsciiWireframe(input.screen_name, layout);

  const payload = {
    screen_name: input.screen_name,
    ascii_diagram: wireframeAscii,
    annotations: [
      { region: 'header', description: 'Navigation and branding' },
      { region: 'main', description: 'Primary content area' },
      { region: 'sidebar', description: 'Filters or metadata' },
      { region: 'footer', description: 'Additional links and info' },
    ],
    components_used: ['Header', 'Navigation', 'Card', 'Button', 'Input'],
  };

  return createStructuredPayload({
    tool: 'generate_wireframe',
    agent: 'pixelfera',
    payload,
    instructions: 'Use this wireframe as starting point for visual design. Review layout and refine component placement.',
    context_for_llm: `Wireframe for screen: ${input.screen_name}. Layout: ${layout}. Contains ${payload.components_used.length} component types. Annotated regions: ${payload.annotations.map((a) => a.region).join(', ')}.`,
    feature_id: input.feature_id,
    related_tools: ['generate_ux_writing', 'create_design_tokens', 'suggest_ui_components'],
  });
}

function generateAsciiWireframe(screenName: string, layout: string): string {
  const singleColumn = `
┌─────────────────────────────────────────┐
│ HEADER / NAVIGATION                     │
├─────────────────────────────────────────┤
│                                         │
│  ${screenName.padEnd(36)}      │
│  Main Content Area                      │
│  - Item 1                               │
│  - Item 2                               │
│  - Item 3                               │
│                                         │
├─────────────────────────────────────────┤
│ FOOTER                                  │
└─────────────────────────────────────────┘
`;

  const twoColumn = `
┌──────────────┬──────────────────────────┐
│   HEADER / NAVIGATION                   │
├──────────────┬──────────────────────────┤
│              │                          │
│  Sidebar     │  ${screenName.padEnd(22)}│
│  - Filter 1  │  Main Content Area       │
│  - Filter 2  │  - Item 1                │
│  - Filter 3  │  - Item 2                │
│              │  - Item 3                │
├──────────────┼──────────────────────────┤
│ FOOTER                                  │
└──────────────┴──────────────────────────┘
`;

  return layout === 'two-column' ? twoColumn : singleColumn;
}
