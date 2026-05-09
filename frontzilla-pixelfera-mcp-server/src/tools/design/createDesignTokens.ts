import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { CreateDesignTokensSchema } from '../../schemas/design.schema.js';

export async function createDesignTokens(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = CreateDesignTokensSchema.parse(args);

  const theme = input.theme || 'light';
  const tokens = {
    colors: {
      primary: theme === 'dark' ? '#3b82f6' : '#2563eb',
      secondary: theme === 'dark' ? '#8b5cf6' : '#7c3aed',
      neutral: theme === 'dark' ? '#e5e7eb' : '#1f2937',
    },
    typography: {
      'heading-1': {
        family: 'Inter, system-ui',
        size: '32px',
        weight: '700',
        line_height: '1.2',
      },
      'heading-2': {
        family: 'Inter, system-ui',
        size: '24px',
        weight: '600',
        line_height: '1.3',
      },
      body: {
        family: 'Inter, system-ui',
        size: '16px',
        weight: '400',
        line_height: '1.5',
      },
    },
    spacing: {
      'xs': '4px',
      'sm': '8px',
      'md': '16px',
      'lg': '24px',
      'xl': '32px',
    },
    shadows: {
      'sm': '0 1px 2px rgba(0,0,0,0.05)',
      'md': '0 4px 6px rgba(0,0,0,0.1)',
      'lg': '0 10px 15px rgba(0,0,0,0.1)',
    },
    radius: {
      'sm': '4px',
      'md': '8px',
      'lg': '12px',
      'xl': '16px',
    },
    animation: {
      'fade-in': 'fade-in 0.3s ease-in',
      'slide-in': 'slide-in 0.3s ease-out',
      'bounce': 'bounce 0.5s ease-in-out',
    },
  };

  let designTokenId: string | undefined;
  if (input.feature_id) {
    const token = store.createDesignTokens(
      input.brand || 'default',
      tokens,
      'css-vars',
      input.feature_id
    );
    designTokenId = token.id;
  }

  return createStructuredPayload({
    tool: 'create_design_tokens',
    agent: 'pixelfera',
    payload: {
      tokens,
      css_variables: Object.entries(tokens.colors)
        .map(([k, v]) => `--color-${k}: ${v};`)
        .join('\n'),
      tailwind_config: {
        colors: tokens.colors,
        spacing: tokens.spacing,
      },
    },
    instructions: 'Export tokens to design tool and code. Share with FrontZilla for implementation.',
    context_for_llm: `Design tokens for theme: ${theme}. Colors: ${Object.keys(tokens.colors).join(', ')}. Spacing scale: ${Object.keys(tokens.spacing).join(', ')}.`,
    feature_id: input.feature_id,
    component_id: designTokenId,
    related_tools: ['generate_component_spec', 'validate_design_system_usage'],
  });
}
