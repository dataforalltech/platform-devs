import { Tool } from '@modelcontextprotocol/sdk/types';
import { FrontzillaPixelferaStore } from '../db/store.js';
import { Settings } from '../config/settings.js';

// Requirements tools
import { analyzeRequirement } from './requirements/analyzeRequirement.js';
import { splitDesignAndFrontendTasks } from './requirements/splitTasks.js';
import { generateFeatureSpec } from './requirements/generateFeatureSpec.js';
import { generateScreenBrief } from './requirements/generateScreenBrief.js';

// Design tools
import { generateWireframe } from './design/generateWireframe.js';
import { createDesignTokens } from './design/createDesignTokens.js';
import { suggestUiComponents } from './design/suggestUiComponents.js';
import { generateUxWriting } from './design/generateUxWriting.js';
import { mapVisualStates } from './design/mapVisualStates.js';
import { reviewUiConsistency } from './design/reviewUiConsistency.js';
import { validateVisualAccessibility } from './design/validateVisualAccessibility.js';

// Frontend tools
import { generateReactComponent } from './frontend/generateReactComponent.js';
import { generateNextjsPage } from './frontend/generateNextjsPage.js';
import { generateTypescriptTypes } from './frontend/generateTypescriptTypes.js';
import { generateApiService } from './frontend/generateApiService.js';
import { generateCustomHook } from './frontend/generateCustomHook.js';
import { generateFormWithValidation } from './frontend/generateFormWithValidation.js';
import { generateFrontendTests } from './frontend/generateFrontendTests.js';
import { reviewFrontendCode } from './frontend/reviewFrontendCode.js';
import { suggestRefactor } from './frontend/suggestRefactor.js';

// Design System tools
import { generateComponentSpec } from './design-system/generateComponentSpec.js';
import { generateComponentVariants } from './design-system/generateComponentVariants.js';
import { documentComponent } from './design-system/documentComponent.js';
import { validateDesignSystemUsage } from './design-system/validateDesignSystemUsage.js';
import { generateStorybookStory } from './design-system/generateStorybookStory.js';

// Workflow tools
import { runUiFeatureWorkflow } from './workflows/runUiFeatureWorkflow.js';

export const TOOL_SCHEMAS: Record<string, Record<string, unknown>> = {
  // Requirements (4)
  analyze_requirement: {
    description: 'Analisa um requisito de feature: identifica telas, fluxos, atores, complexidade',
    inputSchema: {
      type: 'object',
      properties: {
        requirement: { type: 'string', description: 'Descrição do requisito' },
        context: { type: 'string', description: 'Contexto adicional (opcional)' },
      },
      required: ['requirement'],
    },
  },
  split_design_and_frontend_tasks: {
    description: 'Divide uma feature em tarefas para PixelFera (design) e FrontZilla (frontend)',
    inputSchema: {
      type: 'object',
      properties: {
        feature_id: { type: 'string', description: 'ID da feature (feat_...)' },
      },
      required: ['feature_id'],
    },
  },
  generate_feature_spec: {
    description: 'Gera especificação completa de feature: wireframes, APIs, componentes',
    inputSchema: {
      type: 'object',
      properties: {
        feature_id: { type: 'string', description: 'ID da feature (feat_...)' },
        detail_level: {
          type: 'string',
          enum: ['minimal', 'standard', 'detailed'],
          description: 'Nível de detalhe',
        },
      },
      required: ['feature_id'],
    },
  },
  generate_screen_brief: {
    description: 'Gera brief de uma tela: layout, estados, interações',
    inputSchema: {
      type: 'object',
      properties: {
        feature_id: { type: 'string', description: 'ID da feature (feat_...)' },
        screen_name: { type: 'string', description: 'Nome da tela' },
      },
      required: ['feature_id', 'screen_name'],
    },
  },

  // Design / PixelFera (7)
  generate_wireframe: {
    description: 'Gera wireframe ASCII de uma tela com anotações',
    inputSchema: {
      type: 'object',
      properties: {
        screen_name: { type: 'string', description: 'Nome da tela' },
        feature_id: { type: 'string', description: 'ID da feature (opcional)' },
        layout: {
          type: 'string',
          enum: ['single-column', 'two-column', 'three-column', 'grid', 'card'],
          description: 'Tipo de layout',
        },
      },
      required: ['screen_name'],
    },
  },
  create_design_tokens: {
    description: 'Cria design tokens: cores, tipografia, espaçamento, sombras, animações',
    inputSchema: {
      type: 'object',
      properties: {
        feature_id: { type: 'string', description: 'ID da feature (opcional)' },
        brand: { type: 'string', description: 'Nome da marca' },
        theme: { type: 'string', enum: ['light', 'dark', 'auto'], description: 'Tema' },
      },
    },
  },
  suggest_ui_components: {
    description: 'Sugere componentes UI para uma tela',
    inputSchema: {
      type: 'object',
      properties: {
        screen_name: { type: 'string', description: 'Nome da tela' },
        feature_id: { type: 'string', description: 'ID da feature (opcional)' },
      },
      required: ['screen_name'],
    },
  },
  generate_ux_writing: {
    description: 'Gera microcopy: labels, erros, CTAs, empty states',
    inputSchema: {
      type: 'object',
      properties: {
        context: { type: 'string', description: 'Contexto para geração de copy' },
        tone: { type: 'string', enum: ['professional', 'casual', 'friendly', 'technical'] },
        elements: { type: 'array', items: { type: 'string' }, description: 'Elementos a escrever' },
      },
      required: ['context'],
    },
  },
  map_visual_states: {
    description: 'Mapeia estados visuais de um componente: default, hover, loading, error, success, disabled',
    inputSchema: {
      type: 'object',
      properties: {
        component_name: { type: 'string', description: 'Nome do componente' },
        feature_id: { type: 'string', description: 'ID da feature (opcional)' },
      },
      required: ['component_name'],
    },
  },
  review_ui_consistency: {
    description: 'Revisa consistência de UI entre componentes',
    inputSchema: {
      type: 'object',
      properties: {
        components: { type: 'array', items: { type: 'string' }, description: 'Lista de componentes' },
        design_system: { type: 'object', description: 'Design system de referência' },
      },
      required: ['components'],
    },
  },
  validate_visual_accessibility: {
    description: 'Valida acessibilidade visual (WCAG 2.1)',
    inputSchema: {
      type: 'object',
      properties: {
        component_name: { type: 'string', description: 'Nome do componente' },
        spec: { type: 'object', description: 'Especificação visual (opcional)' },
      },
      required: ['component_name'],
    },
  },

  // Frontend / FrontZilla (9)
  generate_react_component: {
    description: 'Gera scaffold de componente React (.tsx)',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Nome do componente (PascalCase)' },
        props: { type: 'array', items: { type: 'object' }, description: 'Props do componente' },
        variant: { type: 'string', description: 'Variante do componente' },
        styling: { type: 'string', enum: ['tailwind', 'styled-components', 'emotion', 'css-modules'] },
      },
      required: ['name'],
    },
  },
  generate_nextjs_page: {
    description: 'Gera página Next.js 14+ com App Router',
    inputSchema: {
      type: 'object',
      properties: {
        route: { type: 'string', description: 'Rota da página' },
        feature_id: { type: 'string', description: 'ID da feature (opcional)' },
        type: { type: 'string', enum: ['app-route', 'layout', 'error', 'loading'] },
      },
      required: ['route'],
    },
  },
  generate_typescript_types: {
    description: 'Gera tipos TypeScript + Zod schema',
    inputSchema: {
      type: 'object',
      properties: {
        entity_name: { type: 'string', description: 'Nome da entidade' },
        fields: { type: 'array', items: { type: 'object' }, description: 'Campos da entidade' },
        pattern: { type: 'string', enum: ['interface', 'type', 'enum'] },
      },
      required: ['entity_name'],
    },
  },
  generate_api_service: {
    description: 'Gera serviço de API com tipos e error handling',
    inputSchema: {
      type: 'object',
      properties: {
        entity: { type: 'string', description: 'Entidade/recurso' },
        endpoints: { type: 'array', items: { type: 'object' }, description: 'Endpoints da API' },
        base_url: { type: 'string', description: 'URL base da API' },
      },
      required: ['entity'],
    },
  },
  generate_custom_hook: {
    description: 'Gera custom hook React com tipagem completa',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Nome do hook (useXxx)' },
        purpose: { type: 'string', description: 'Propósito do hook' },
        dependencies: { type: 'array', items: { type: 'string' }, description: 'Dependências' },
      },
      required: ['name', 'purpose'],
    },
  },
  generate_form_with_validation: {
    description: 'Gera formulário React com validação (React Hook Form + Zod)',
    inputSchema: {
      type: 'object',
      properties: {
        form_name: { type: 'string', description: 'Nome do formulário' },
        fields: {
          type: 'array',
          items: { type: 'object' },
          description: 'Campos do formulário',
        },
        library: { type: 'string', enum: ['react-hook-form', 'formik', 'react-final-form'] },
      },
      required: ['form_name', 'fields'],
    },
  },
  generate_frontend_tests: {
    description: 'Gera testes unitários e E2E para componentes',
    inputSchema: {
      type: 'object',
      properties: {
        component_name: { type: 'string', description: 'Nome do componente' },
        test_type: { type: 'string', enum: ['unit', 'integration', 'e2e'] },
      },
      required: ['component_name'],
    },
  },
  review_frontend_code: {
    description: 'Revisa código frontend: performance, acessibilidade, segurança, tipos',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: 'Código para revisar' },
        lang: { type: 'string', enum: ['typescript', 'jsx', 'tsx'] },
        focus: {
          type: 'array',
          items: { type: 'string' },
          description: 'Áreas para focar na revisão',
        },
      },
      required: ['code'],
    },
  },
  suggest_refactor: {
    description: 'Sugere plano de refatoração de código',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: 'Código para refatorar' },
        goal: { type: 'string', description: 'Objetivo da refatoração' },
      },
      required: ['code'],
    },
  },

  // Design System (5)
  generate_component_spec: {
    description: 'Gera especificação de componente para design system',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Nome do componente' },
        category: { type: 'string', enum: ['atom', 'molecule', 'organism', 'template', 'page'] },
        feature_id: { type: 'string', description: 'ID da feature (opcional)' },
      },
      required: ['name', 'category'],
    },
  },
  generate_component_variants: {
    description: 'Gera variações de um componente (size, color, intent, shape)',
    inputSchema: {
      type: 'object',
      properties: {
        component_id: { type: 'string', description: 'ID do componente (comp_...)' },
      },
      required: ['component_id'],
    },
  },
  document_component: {
    description: 'Documenta componente em markdown com props, exemplos, do/dont',
    inputSchema: {
      type: 'object',
      properties: {
        component_id: { type: 'string', description: 'ID do componente (comp_...)' },
      },
      required: ['component_id'],
    },
  },
  validate_design_system_usage: {
    description: 'Valida conformidade com design system em código',
    inputSchema: {
      type: 'object',
      properties: {
        code: { type: 'string', description: 'Código para validar' },
        design_system: { type: 'object', description: 'Design system de referência' },
      },
      required: ['code'],
    },
  },
  generate_storybook_story: {
    description: 'Gera Storybook story (CSF 3.0) para componente',
    inputSchema: {
      type: 'object',
      properties: {
        component_name: { type: 'string', description: 'Nome do componente' },
        component_id: { type: 'string', description: 'ID do componente (opcional)' },
      },
      required: ['component_name'],
    },
  },

  // Workflow (1)
  run_ui_feature_workflow: {
    description: 'Orquestra workflow completo: análise → design → frontend → integração',
    inputSchema: {
      type: 'object',
      properties: {
        requirement: { type: 'string', description: 'Requisito da feature' },
        context: { type: 'string', description: 'Contexto adicional' },
        target: { type: 'string', enum: ['analysis', 'design', 'frontend', 'complete'] },
        stack: { type: 'string', enum: ['react', 'nextjs', 'vue', 'svelte'] },
      },
      required: ['requirement'],
    },
  },
};

export function getToolSchemas(): Tool[] {
  return Object.entries(TOOL_SCHEMAS).map(([name, schema]) => ({
    name,
    description: (schema as Record<string, unknown>).description as string,
    inputSchema: (schema as Record<string, unknown>).inputSchema as Record<string, unknown>,
  })) as Tool[];
}

export async function dispatchTool(
  toolName: string,
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore,
  _settings: Settings
): Promise<Record<string, unknown>> {
  switch (toolName) {
    // Requirements
    case 'analyze_requirement':
      return await analyzeRequirement(args, store);
    case 'split_design_and_frontend_tasks':
      return await splitDesignAndFrontendTasks(args, store);
    case 'generate_feature_spec':
      return await generateFeatureSpec(args, store);
    case 'generate_screen_brief':
      return await generateScreenBrief(args, store);

    // Design
    case 'generate_wireframe':
      return await generateWireframe(args, store);
    case 'create_design_tokens':
      return await createDesignTokens(args, store);
    case 'suggest_ui_components':
      return await suggestUiComponents(args, store);
    case 'generate_ux_writing':
      return await generateUxWriting(args, store);
    case 'map_visual_states':
      return await mapVisualStates(args, store);
    case 'review_ui_consistency':
      return await reviewUiConsistency(args, store);
    case 'validate_visual_accessibility':
      return await validateVisualAccessibility(args, store);

    // Frontend
    case 'generate_react_component':
      return await generateReactComponent(args, store);
    case 'generate_nextjs_page':
      return await generateNextjsPage(args, store);
    case 'generate_typescript_types':
      return await generateTypescriptTypes(args, store);
    case 'generate_api_service':
      return await generateApiService(args, store);
    case 'generate_custom_hook':
      return await generateCustomHook(args, store);
    case 'generate_form_with_validation':
      return await generateFormWithValidation(args, store);
    case 'generate_frontend_tests':
      return await generateFrontendTests(args, store);
    case 'review_frontend_code':
      return await reviewFrontendCode(args, store);
    case 'suggest_refactor':
      return await suggestRefactor(args, store);

    // Design System
    case 'generate_component_spec':
      return await generateComponentSpec(args, store);
    case 'generate_component_variants':
      return await generateComponentVariants(args, store);
    case 'document_component':
      return await documentComponent(args, store);
    case 'validate_design_system_usage':
      return await validateDesignSystemUsage(args, store);
    case 'generate_storybook_story':
      return await generateStorybookStory(args, store);

    // Workflow
    case 'run_ui_feature_workflow':
      return await runUiFeatureWorkflow(args, store);

    default:
      return { error: 'unknown_tool', tool: toolName };
  }
}
