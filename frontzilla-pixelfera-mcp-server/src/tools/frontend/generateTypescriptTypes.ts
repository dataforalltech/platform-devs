import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateTypescriptTypesSchema } from '../../schemas/frontend.schema.js';

export async function generateTypescriptTypes(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateTypescriptTypesSchema.parse(args);

  const typescriptCode = `import { z } from 'zod';

export interface ${input.entity_name} {
  ${input.fields?.map((f) => `${f.name}: ${f.type};`).join('\n  ') || 'id: string;'}
}

export const ${input.entity_name}Schema = z.object({
  ${input.fields?.map((f) => `${f.name}: z.${f.type.includes('string') ? 'string()' : 'unknown()'}`).join('\n  ') || 'id: z.string(),'}
});

export type ${input.entity_name}Input = z.infer<typeof ${input.entity_name}Schema>;
`;

  const payload = {
    code: typescriptCode,
    type_name: input.entity_name,
    zod_schema: `${input.entity_name}Schema`,
  };

  return createStructuredPayload({
    tool: 'generate_typescript_types',
    agent: 'frontzilla',
    payload,
    instructions: 'Import types and schema in API services and components. Use for validation.',
    context_for_llm: `TypeScript types for entity: ${input.entity_name}. ${input.fields?.length || 0} fields. Includes Zod schema.`,
    related_tools: ['generate_api_service', 'generate_form_with_validation'],
  });
}
