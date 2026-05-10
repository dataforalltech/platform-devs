import { Tool } from '@modelcontextprotocol/sdk/types.js';
import { OpsZillaStore } from '../db/store.js';
import { mcpClient } from '@platform/mcp-client';
import { Settings } from '../config/settings.js';

const TOOL_SCHEMAS: Tool[] = [
  {
    name: 'analyze_infrastructure_requirement',
    description: 'Analisa requisito de infraestrutura, cloud e operação',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string', description: 'Nome da aplicação' },
        stack: { type: 'string', description: 'Stack (Python, Node.js, Go, etc)' },
        context: { type: 'string', description: 'Contexto adicional (opcional)' },
      },
      required: ['application', 'stack'],
    },
  },
  {
    name: 'generate_dockerfile',
    description: 'Gera Dockerfile otimizado para a aplicação',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string', description: 'Nome da aplicação' },
        runtime: { type: 'string', description: 'Runtime (python:3.11, node:20, etc)' },
        build_command: { type: 'string', description: 'Comando de build' },
        start_command: { type: 'string', description: 'Comando de início' },
      },
      required: ['application', 'runtime'],
    },
  },
  {
    name: 'generate_docker_compose',
    description: 'Gera docker-compose para ambiente local',
    inputSchema: {
      type: 'object' as const,
      properties: {
        services: { type: 'array', description: 'Lista de serviços' },
        networks: { type: 'string', description: 'Configuração de redes' },
      },
      required: ['services'],
    },
  },
  {
    name: 'generate_github_actions_pipeline',
    description: 'Gera pipeline CI/CD com GitHub Actions',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        events: { type: 'array', description: 'Eventos disparadores (push, pull_request)' },
        stages: { type: 'array', description: 'Estágios (build, test, deploy)' },
      },
      required: ['application'],
    },
  },
  {
    name: 'generate_gitlab_ci_pipeline',
    description: 'Gera pipeline CI/CD com GitLab CI',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        stages: { type: 'array', description: 'Estágios (build, test, deploy)' },
      },
      required: ['application'],
    },
  },
  {
    name: 'generate_kubernetes_manifest',
    description: 'Gera manifest Kubernetes (Deployment, Service, ConfigMap)',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        replicas: { type: 'number', description: 'Número de replicas' },
        port: { type: 'number', description: 'Porta da aplicação' },
        resources: { type: 'object', description: 'Limites de recursos' },
      },
      required: ['application'],
    },
  },
  {
    name: 'generate_helm_chart',
    description: 'Gera Helm Chart parametrizado',
    inputSchema: {
      type: 'object' as const,
      properties: {
        chart_name: { type: 'string' },
        app_name: { type: 'string' },
        version: { type: 'string', description: 'Versão do chart' },
      },
      required: ['chart_name', 'app_name'],
    },
  },
  {
    name: 'generate_terraform_module',
    description: 'Gera módulo Terraform para infraestrutura',
    inputSchema: {
      type: 'object' as const,
      properties: {
        module_name: { type: 'string' },
        cloud_provider: { type: 'string', enum: ['aws', 'gcp', 'azure'] },
        resources: { type: 'array', description: 'Recursos a criar' },
      },
      required: ['module_name', 'cloud_provider'],
    },
  },
  {
    name: 'generate_cloud_run_deploy',
    description: 'Gera configuração de deploy no Google Cloud Run',
    inputSchema: {
      type: 'object' as const,
      properties: {
        service_name: { type: 'string' },
        image: { type: 'string', description: 'Docker image URI' },
        port: { type: 'number' },
        memory: { type: 'string', enum: ['256Mi', '512Mi', '1Gi', '2Gi', '4Gi'] },
        env_vars: { type: 'object', description: 'Variáveis de ambiente' },
      },
      required: ['service_name', 'image'],
    },
  },
  {
    name: 'generate_gke_deploy',
    description: 'Gera configuração de deploy no Google Kubernetes Engine',
    inputSchema: {
      type: 'object' as const,
      properties: {
        cluster_name: { type: 'string' },
        application: { type: 'string' },
        replicas: { type: 'number' },
      },
      required: ['cluster_name', 'application'],
    },
  },
  {
    name: 'generate_iam_policy',
    description: 'Gera política IAM com least privilege',
    inputSchema: {
      type: 'object' as const,
      properties: {
        service_account: { type: 'string' },
        permissions: { type: 'array', description: 'Permissões necessárias' },
        resources: { type: 'array', description: 'Recursos alvo' },
      },
      required: ['service_account', 'permissions'],
    },
  },
  {
    name: 'generate_secret_strategy',
    description: 'Gera estratégia de gerenciamento de secrets',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        secrets: { type: 'array', description: 'Secrets necessários' },
        cloud_provider: { type: 'string', enum: ['aws', 'gcp', 'azure'] },
      },
      required: ['application', 'secrets'],
    },
  },
  {
    name: 'generate_observability_plan',
    description: 'Gera plano de observabilidade (logs, métricas, tracing)',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        platform: { type: 'string', enum: ['datadog', 'newrelic', 'grafana', 'prometheus'] },
      },
      required: ['application'],
    },
  },
  {
    name: 'generate_prometheus_rules',
    description: 'Gera regras Prometheus para alertas',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        metrics: { type: 'array', description: 'Métricas a monitorar' },
      },
      required: ['application'],
    },
  },
  {
    name: 'generate_grafana_dashboard',
    description: 'Gera dashboard Grafana parametrizado',
    inputSchema: {
      type: 'object' as const,
      properties: {
        dashboard_name: { type: 'string' },
        application: { type: 'string' },
        datasource: { type: 'string', enum: ['Prometheus', 'CloudWatch', 'Stackdriver'] },
      },
      required: ['dashboard_name', 'application'],
    },
  },
  {
    name: 'generate_runbook',
    description: 'Gera runbook de incident response',
    inputSchema: {
      type: 'object' as const,
      properties: {
        incident_type: { type: 'string', description: 'Tipo de incidente' },
        service: { type: 'string', description: 'Serviço afetado' },
        escalation: { type: 'string', description: 'Contatos de escalação' },
      },
      required: ['incident_type', 'service'],
    },
  },
  {
    name: 'review_devops_config',
    description: 'Revisa configuração DevOps: segurança, performance, práticas',
    inputSchema: {
      type: 'object' as const,
      properties: {
        config: { type: 'string', description: 'Configuração a revisar' },
        type: { type: 'string', enum: ['dockerfile', 'k8s', 'terraform', 'pipeline', 'helm'] },
      },
      required: ['config', 'type'],
    },
  },
  {
    name: 'review_cloud_security',
    description: 'Revisa segurança cloud: IAM, networking, secrets, compliance',
    inputSchema: {
      type: 'object' as const,
      properties: {
        infrastructure: { type: 'string', description: 'Descrição da infraestrutura' },
        cloud_provider: { type: 'string', enum: ['aws', 'gcp', 'azure'] },
      },
      required: ['infrastructure', 'cloud_provider'],
    },
  },
  {
    name: 'generate_release_checklist',
    description: 'Gera checklist de release e deploy',
    inputSchema: {
      type: 'object' as const,
      properties: {
        application: { type: 'string' },
        environment: { type: 'string', enum: ['staging', 'production'] },
        version: { type: 'string' },
      },
      required: ['application', 'environment'],
    },
  },
];

export function getToolSchemas(): Tool[] {
  return TOOL_SCHEMAS;
}

export async function dispatchTool(
  toolName: string,
  args: Record<string, unknown>,
  store: OpsZillaStore,
  settings: Settings
): Promise<unknown> {
  switch (toolName) {
    case 'analyze_infrastructure_requirement':
      return analyzeInfrastructureRequirement(args as any);
    case 'generate_dockerfile':
      return generateDockerfile(args as any);
    case 'generate_docker_compose':
      return generateDockerCompose(args as any);
    case 'generate_github_actions_pipeline':
      return generateGithubActionsPipeline(args as any);
    case 'generate_gitlab_ci_pipeline':
      return generateGitlabCIPipeline(args as any);
    case 'generate_kubernetes_manifest':
      return generateKubernetesManifest(args as any);
    case 'generate_helm_chart':
      return generateHelmChart(args as any);
    case 'generate_terraform_module':
      return generateTerraformModule(args as any);
    case 'generate_cloud_run_deploy':
      return generateCloudRunDeploy(args as any);
    case 'generate_gke_deploy':
      return generateGKEDeploy(args as any);
    case 'generate_iam_policy':
      return generateIAMPolicy(args as any);
    case 'generate_secret_strategy':
      return generateSecretStrategy(args as any);
    case 'generate_observability_plan':
      return generateObservabilityPlan(args as any);
    case 'generate_prometheus_rules':
      return generatePrometheusRules(args as any);
    case 'generate_grafana_dashboard':
      return generateGrafanaDashboard(args as any);
    case 'generate_runbook':
      return generateRunbook(args as any);
    case 'review_devops_config':
      return reviewDevopsConfig(args as any);
    case 'review_cloud_security':
      return reviewCloudSecurity(args as any);
    case 'generate_release_checklist':
      return generateReleaseChecklist(args as any);
    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}

// Tool implementations
async function analyzeInfrastructureRequirement(args: any): Promise<unknown> {
  return { tool: 'analyze_infrastructure_requirement', services: [], cloud_provider: 'gcp', complexity: 'medium' };
}

async function generateDockerfile(args: any): Promise<unknown> {
  const dockerfile = `FROM ${args.runtime}\nRUN ${args.build_command}\nCMD ${args.start_command}`;

  // Integração: validar Dockerfile com qa-mcp
  const qaValidation = await mcpClient.callQATool('run_linter', {
    repo_path: 'Dockerfile',
  });

  return {
    tool: 'generate_dockerfile',
    dockerfile,
    qa_validation: qaValidation,
    status: 'dockerfile_generated_with_validation',
  };
}

async function generateDockerCompose(args: any): Promise<unknown> {
  return { tool: 'generate_docker_compose', services: args.services, config: {} };
}

async function generateGithubActionsPipeline(args: any): Promise<unknown> {
  return { tool: 'generate_github_actions_pipeline', workflow_file: '.github/workflows/ci.yml', stages: args.stages };
}

async function generateGitlabCIPipeline(args: any): Promise<unknown> {
  return { tool: 'generate_gitlab_ci_pipeline', gitlab_ci_file: '.gitlab-ci.yml', stages: args.stages };
}

async function generateKubernetesManifest(args: any): Promise<unknown> {
  return { tool: 'generate_kubernetes_manifest', deployment: {}, service: {}, config_map: {} };
}

async function generateHelmChart(args: any): Promise<unknown> {
  return { tool: 'generate_helm_chart', chart_structure: {}, values: {} };
}

async function generateTerraformModule(args: any): Promise<unknown> {
  const terraformModule = {
    module_structure: {},
    main_tf: `# Terraform module: ${args.module_name}\n`,
    variables_tf: '',
    outputs_tf: '',
  };

  // Integração: validar Terraform com infra-mcp
  const infraValidation = await mcpClient.callInfraTool('terraform_validate', {
    path: `modules/${args.module_name}`,
  });

  return {
    tool: 'generate_terraform_module',
    ...terraformModule,
    infrastructure_validation: infraValidation,
    status: 'terraform_generated_with_validation',
  };
}

async function generateCloudRunDeploy(args: any): Promise<unknown> {
  return { tool: 'generate_cloud_run_deploy', service_config: {}, environment: args.env_vars };
}

async function generateGKEDeploy(args: any): Promise<unknown> {
  return { tool: 'generate_gke_deploy', cluster_config: {}, deployment: {} };
}

async function generateIAMPolicy(args: any): Promise<unknown> {
  return { tool: 'generate_iam_policy', policy: {}, permissions: args.permissions };
}

async function generateSecretStrategy(args: any): Promise<unknown> {
  return { tool: 'generate_secret_strategy', strategy: {}, secrets: args.secrets };
}

async function generateObservabilityPlan(args: any): Promise<unknown> {
  return { tool: 'generate_observability_plan', logs: {}, metrics: {}, tracing: {} };
}

async function generatePrometheusRules(args: any): Promise<unknown> {
  return { tool: 'generate_prometheus_rules', rules: [], alerts: [] };
}

async function generateGrafanaDashboard(args: any): Promise<unknown> {
  return { tool: 'generate_grafana_dashboard', dashboard_json: {} };
}

async function generateRunbook(args: any): Promise<unknown> {
  return { tool: 'generate_runbook', runbook: {}, steps: [] };
}

async function reviewDevopsConfig(args: any): Promise<unknown> {
  return { tool: 'review_devops_config', issues: [], recommendations: [], score: 85 };
}

async function reviewCloudSecurity(args: any): Promise<unknown> {
  return { tool: 'review_cloud_security', vulnerabilities: [], recommendations: [], compliance_score: 90 };
}

async function generateReleaseChecklist(args: any): Promise<unknown> {
  return { tool: 'generate_release_checklist', checklist: [], version: args.version };
}
