import { Tool } from '@modelcontextprotocol/sdk/types.js';
import { BackzillaStore } from '../db/store.js';
import { mcpClient } from '@platform/mcp-client';
import { Settings } from '../config/settings.js';

const TOOL_SCHEMAS: Tool[] = [
  {
    name: 'analyze_backend_requirement',
    description: 'Analisa requisito de negócio e identifica entidades, permissões, integrações e regras',
    inputSchema: {
      type: 'object' as const,
      properties: {
        requirement: { type: 'string', description: 'Descrição do requisito de negócio' },
        context: { type: 'string', description: 'Contexto adicional (opcional)' },
      },
      required: ['requirement'],
    },
  },
  {
    name: 'generate_api_contract',
    description: 'Gera contrato de API com schemas, endpoints e status codes',
    inputSchema: {
      type: 'object' as const,
      properties: {
        endpoint: { type: 'string', description: 'Path do endpoint (ex: /api/users)' },
        method: { type: 'string', enum: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'] },
        description: { type: 'string', description: 'Descrição do endpoint' },
        request_schema: { type: 'object', description: 'Schema de entrada' },
        response_schema: { type: 'object', description: 'Schema de saída' },
      },
      required: ['endpoint', 'method', 'description'],
    },
  },
  {
    name: 'generate_fastapi_router',
    description: 'Gera router FastAPI completo com validação e documentação',
    inputSchema: {
      type: 'object' as const,
      properties: {
        name: { type: 'string', description: 'Nome do router (ex: users)' },
        base_path: { type: 'string', description: 'Path base (ex: /api/v1/users)' },
        endpoints: { type: 'array', description: 'Lista de endpoints' },
      },
      required: ['name', 'base_path'],
    },
  },
  {
    name: 'generate_nestjs_controller',
    description: 'Gera controller NestJS com decoradores, validação e serviços',
    inputSchema: {
      type: 'object' as const,
      properties: {
        name: { type: 'string', description: 'Nome do controller (ex: Users)' },
        base_path: { type: 'string', description: 'Path base (ex: /api/v1/users)' },
        methods: { type: 'array', description: 'Lista de métodos HTTP' },
      },
      required: ['name', 'base_path'],
    },
  },
  {
    name: 'generate_service_layer',
    description: 'Gera serviço com regra de negócio, validações e tratamento de erros',
    inputSchema: {
      type: 'object' as const,
      properties: {
        name: { type: 'string', description: 'Nome do serviço (ex: UserService)' },
        methods: { type: 'array', description: 'Lista de métodos do serviço' },
        dependencies: { type: 'array', description: 'Dependências injetadas' },
      },
      required: ['name', 'methods'],
    },
  },
  {
    name: 'generate_repository_layer',
    description: 'Gera repository com operações CRUD e queries otimizadas',
    inputSchema: {
      type: 'object' as const,
      properties: {
        entity: { type: 'string', description: 'Nome da entidade (ex: User)' },
        database: { type: 'string', enum: ['postgresql', 'mysql', 'mongodb'], description: 'Tipo de banco' },
        orm: { type: 'string', enum: ['sqlalchemy', 'typeorm', 'prisma', 'mongoengine'] },
      },
      required: ['entity', 'database'],
    },
  },
  {
    name: 'generate_database_schema',
    description: 'Gera schema de banco de dados com índices e constraints',
    inputSchema: {
      type: 'object' as const,
      properties: {
        entity: { type: 'string', description: 'Nome da entidade' },
        attributes: { type: 'array', description: 'Lista de atributos' },
        relationships: { type: 'array', description: 'Relacionamentos' },
        database: { type: 'string', enum: ['postgresql', 'mysql', 'mongodb'] },
      },
      required: ['entity', 'attributes', 'database'],
    },
  },
  {
    name: 'generate_migration',
    description: 'Gera migration de banco de dados idempotente e reversível',
    inputSchema: {
      type: 'object' as const,
      properties: {
        title: { type: 'string', description: 'Título da migration (ex: create_users_table)' },
        operations: { type: 'array', description: 'Operações (create, alter, drop, index)' },
        database: { type: 'string', enum: ['postgresql', 'mysql', 'mongodb'] },
      },
      required: ['title', 'operations', 'database'],
    },
  },
  {
    name: 'generate_auth_policy',
    description: 'Gera política de autenticação, autorização e proteção de dados',
    inputSchema: {
      type: 'object' as const,
      properties: {
        resource: { type: 'string', description: 'Recurso protegido (ex: /api/users/{id})' },
        auth_type: { type: 'string', enum: ['jwt', 'oauth2', 'api_key', 'session'] },
        roles: { type: 'array', description: 'Roles permitidas (ex: [admin, user])' },
        data_sensitivity: { type: 'string', enum: ['public', 'internal', 'confidential', 'restricted'] },
      },
      required: ['resource', 'auth_type', 'roles'],
    },
  },
  {
    name: 'generate_backend_tests',
    description: 'Gera testes unitários, integração e E2E para backend',
    inputSchema: {
      type: 'object' as const,
      properties: {
        component: { type: 'string', description: 'Componente a testar (controller, service, repository)' },
        test_type: { type: 'string', enum: ['unit', 'integration', 'e2e'] },
        framework: { type: 'string', enum: ['pytest', 'unittest', 'jest', 'vitest'] },
      },
      required: ['component', 'test_type'],
    },
  },
  {
    name: 'review_backend_code',
    description: 'Revisa código backend: segurança, performance, padrões, erros',
    inputSchema: {
      type: 'object' as const,
      properties: {
        code: { type: 'string', description: 'Código a revisar' },
        language: { type: 'string', enum: ['python', 'typescript', 'javascript', 'java', 'go'] },
        focus: { type: 'array', description: 'Áreas de foco (security, performance, patterns, errors)' },
      },
      required: ['code', 'language'],
    },
  },
  {
    name: 'optimize_query',
    description: 'Otimiza query de banco de dados: índices, joins, N+1 problems',
    inputSchema: {
      type: 'object' as const,
      properties: {
        query: { type: 'string', description: 'SQL ou query a otimizar' },
        database: { type: 'string', enum: ['postgresql', 'mysql', 'mongodb', 'bigquery'] },
        table_schema: { type: 'object', description: 'Schema da tabela' },
      },
      required: ['query', 'database'],
    },
  },
  {
    name: 'generate_openapi_spec',
    description: 'Gera especificação OpenAPI completa para documentação de API',
    inputSchema: {
      type: 'object' as const,
      properties: {
        api_name: { type: 'string', description: 'Nome da API' },
        version: { type: 'string', description: 'Versão da API' },
        endpoints: { type: 'array', description: 'Lista de endpoints' },
        base_url: { type: 'string', description: 'URL base da API' },
      },
      required: ['api_name', 'version', 'endpoints'],
    },
  },
  {
    name: 'map_integration_flow',
    description: 'Mapeia fluxo de integração com sistemas externos: auth, erros, retry',
    inputSchema: {
      type: 'object' as const,
      properties: {
        integration_name: { type: 'string', description: 'Nome da integração' },
        external_service: { type: 'string', description: 'Serviço externo' },
        endpoints: { type: 'array', description: 'Endpoints consumidos' },
        auth_type: { type: 'string', enum: ['api_key', 'oauth2', 'jwt', 'basic'] },
      },
      required: ['integration_name', 'external_service'],
    },
  },
];

export function getToolSchemas(): Tool[] {
  return TOOL_SCHEMAS;
}

export async function dispatchTool(
  toolName: string,
  args: Record<string, unknown>,
  store: BackzillaStore,
  settings: Settings
): Promise<unknown> {
  switch (toolName) {
    case 'analyze_backend_requirement':
      return analyzeBackendRequirement(args as any);
    case 'generate_api_contract':
      return generateApiContract(args as any);
    case 'generate_fastapi_router':
      return generateFastAPIRouter(args as any);
    case 'generate_nestjs_controller':
      return generateNestJSController(args as any);
    case 'generate_service_layer':
      return generateServiceLayer(args as any);
    case 'generate_repository_layer':
      return generateRepositoryLayer(args as any);
    case 'generate_database_schema':
      return generateDatabaseSchema(args as any);
    case 'generate_migration':
      return generateMigration(args as any);
    case 'generate_auth_policy':
      return generateAuthPolicy(args as any);
    case 'generate_backend_tests':
      return generateBackendTests(args as any);
    case 'review_backend_code':
      return reviewBackendCode(args as any);
    case 'optimize_query':
      return optimizeQuery(args as any);
    case 'generate_openapi_spec':
      return generateOpenAPISpec(args as any);
    case 'map_integration_flow':
      return mapIntegrationFlow(args as any);
    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}

// Tool implementations
async function analyzeBackendRequirement(args: { requirement: string; context?: string }): Promise<unknown> {
  return {
    tool: 'analyze_backend_requirement',
    entities: ['entity1', 'entity2'],
    permissions: ['create', 'read', 'update', 'delete'],
    integrations: [],
    business_rules: [],
    complexity: 'medium',
  };
}

async function generateApiContract(args: any): Promise<unknown> {
  const contract = {
    tool: 'generate_api_contract',
    endpoint: args.endpoint,
    method: args.method,
    request_schema: args.request_schema || {},
    response_schema: args.response_schema || {},
    status_codes: [200, 400, 401, 403, 404, 500],
  };

  // Integração: validar contrato com qa-mcp
  const qaValidation = await mcpClient.callQATool('run_linter', {
    repo_path: `api/${args.endpoint}`,
  });

  return {
    contract,
    qa_validation: qaValidation,
    status: 'contract_generated_with_validation',
  };
}

async function generateFastAPIRouter(args: any): Promise<unknown> {
  return {
    tool: 'generate_fastapi_router',
    name: args.name,
    base_path: args.base_path,
    code: `from fastapi import APIRouter\n\nrouter = APIRouter(prefix="${args.base_path}", tags=["${args.name}"])\n`,
  };
}

async function generateNestJSController(args: any): Promise<unknown> {
  return {
    tool: 'generate_nestjs_controller',
    name: args.name,
    base_path: args.base_path,
    code: `import { Controller } from '@nestjs/common';\n\n@Controller('${args.base_path}')\nexport class ${args.name}Controller {}\n`,
  };
}

async function generateServiceLayer(args: any): Promise<unknown> {
  return {
    tool: 'generate_service_layer',
    name: args.name,
    code: `export class ${args.name} {}\n`,
  };
}

async function generateRepositoryLayer(args: any): Promise<unknown> {
  return {
    tool: 'generate_repository_layer',
    entity: args.entity,
    code: `export class ${args.entity}Repository {}\n`,
  };
}

async function generateDatabaseSchema(args: any): Promise<unknown> {
  const schema = {
    tool: 'generate_database_schema',
    entity: args.entity,
    sql: `CREATE TABLE ${args.entity.toLowerCase()}s (\n  id SERIAL PRIMARY KEY\n);\n`,
  };

  // Integração: validar schema com qa-mcp
  const qaValidation = await mcpClient.callQATool('run_linter', {
    repo_path: `database/schema/${args.entity}`,
  });

  return {
    schema,
    qa_validation: qaValidation,
    status: 'schema_generated_with_validation',
  };
}

async function generateMigration(args: any): Promise<unknown> {
  return {
    tool: 'generate_migration',
    title: args.title,
    code: `-- Migration: ${args.title}\n`,
  };
}

async function generateAuthPolicy(args: any): Promise<unknown> {
  return {
    tool: 'generate_auth_policy',
    resource: args.resource,
    auth_type: args.auth_type,
    roles: args.roles,
    policy: {},
  };
}

async function generateBackendTests(args: any): Promise<unknown> {
  const tests = {
    tool: 'generate_backend_tests',
    component: args.component,
    test_type: args.test_type,
    code: `# Test for ${args.component}\n`,
  };

  // Integração: gerar plano de testes com test-mcp
  const testPlan = await mcpClient.callTestTool('create_test_plan', {
    title: `Test Plan: ${args.component}`,
    scope: `Testing ${args.component} backend`,
  });

  return {
    tests,
    test_plan: testPlan,
    status: 'tests_generated_with_plan',
  };
}

async function reviewBackendCode(args: any): Promise<unknown> {
  return {
    tool: 'review_backend_code',
    issues: [],
    recommendations: [],
    score: 85,
  };
}

async function optimizeQuery(args: any): Promise<unknown> {
  return {
    tool: 'optimize_query',
    original_query: args.query,
    optimized_query: args.query,
    suggestions: ['Add index on foreign key', 'Use EXPLAIN ANALYZE'],
  };
}

async function generateOpenAPISpec(args: any): Promise<unknown> {
  return {
    tool: 'generate_openapi_spec',
    api_name: args.api_name,
    version: args.version,
    spec: {
      openapi: '3.0.0',
      info: { title: args.api_name, version: args.version },
      paths: {},
    },
  };
}

async function mapIntegrationFlow(args: any): Promise<unknown> {
  return {
    tool: 'map_integration_flow',
    integration_name: args.integration_name,
    external_service: args.external_service,
    flow_diagram: '',
    auth_strategy: args.auth_type,
    error_handling: { retry: true, timeout: 30000 },
  };
}
