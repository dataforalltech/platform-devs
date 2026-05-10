import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateReactComponentSchema } from '../../schemas/frontend.schema.js';

export async function generateReactComponent(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateReactComponentSchema.parse(args);
  const styling = input.styling || 'tailwind';

  const typescriptCode = `import React from 'react';

interface ${input.name}Props {
  ${input.props?.map((p) => `${p.name}?: ${p.type};`).join('\n  ') || ''}
}

export const ${input.name}: React.FC<${input.name}Props> = ({
  ${input.props?.map((p) => p.name).join(', ') || ''}
}) => {
  return (
    <div className="component-${input.name.toLowerCase()}">
      {/* Component content */}
    </div>
  );
};

export default ${input.name};
`;

  const payload = {
    filename: `${input.name}.tsx`,
    typescript_code: typescriptCode,
    exports: [input.name, 'default'],
    props_interface: `${input.name}Props`,
    imports: ['React'],
  };

  return createStructuredPayload({
    tool: 'generate_react_component',
    agent: 'frontzilla',
    payload,
    instructions: 'Expand component logic. Add event handlers, hooks, state management as needed.',
    context_for_llm: `React component scaffold for: ${input.name}. Styling: ${styling}. ${input.props?.length || 0} props.`,
    related_tools: ['generate_typescript_types', 'generate_frontend_tests'],
  });
}
