import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateApiServiceSchema } from '../../schemas/frontend.schema.js';

export async function generateApiService(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateApiServiceSchema.parse(args);
  const baseUrl = input.base_url || 'http://localhost:3000/api';

  const typescriptCode = `import axios from 'axios';

const api = axios.create({
  baseURL: '${baseUrl}',
});

export class ${input.entity}Service {
  static async list() {
    const response = await api.get('/${input.entity.toLowerCase()}');
    return response.data;
  }

  static async get(id: string) {
    const response = await api.get(\`/${input.entity.toLowerCase()}/\${id}\`);
    return response.data;
  }

  static async create(data: unknown) {
    const response = await api.post('/${input.entity.toLowerCase()}', data);
    return response.data;
  }

  static async update(id: string, data: unknown) {
    const response = await api.put(\`/${input.entity.toLowerCase()}/\${id}\`, data);
    return response.data;
  }

  static async delete(id: string) {
    const response = await api.delete(\`/${input.entity.toLowerCase()}/\${id}\`);
    return response.data;
  }
}
`;

  const payload = {
    filename: `${input.entity.toLowerCase()}.service.ts`,
    typescript_code: typescriptCode,
    base_url: baseUrl,
    endpoints: {
      list: { method: 'GET', path: `/${input.entity.toLowerCase()}`, request_type: 'void', response_type: `${input.entity}[]` },
      get: { method: 'GET', path: `/${input.entity.toLowerCase()}/:id`, request_type: 'id: string', response_type: input.entity },
      create: { method: 'POST', path: `/${input.entity.toLowerCase()}`, request_type: `Partial<${input.entity}>`, response_type: input.entity },
      update: { method: 'PUT', path: `/${input.entity.toLowerCase()}/:id`, request_type: `Partial<${input.entity}>`, response_type: input.entity },
      delete: { method: 'DELETE', path: `/${input.entity.toLowerCase()}/:id`, request_type: 'id: string', response_type: 'void' },
    },
  };

  return createStructuredPayload({
    tool: 'generate_api_service',
    agent: 'frontzilla',
    payload,
    instructions: 'Import and use in components. Handle loading and error states.',
    context_for_llm: `API service for entity: ${input.entity}. Base URL: ${baseUrl}. 5 endpoints (CRUD).`,
    related_tools: ['generate_typescript_types', 'generate_custom_hook'],
  });
}
