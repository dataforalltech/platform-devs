import { Pool } from 'pg';
import { v4 as uuidv4 } from 'uuid';

interface PersistenceRule {
  pattern: RegExp;
  table: string;
  idPrefix: string;
  mapFields: (toolName: string, args: Record<string, any>, result: any) => Record<string, any>;
}

const PERSISTENCE_RULES: PersistenceRule[] = [
  // QAZilla - Test Planning
  {
    pattern: /generate_test_plan/,
    table: 'test_plans',
    idPrefix: 'tp',
    mapFields: (toolName, args, result) => ({
      title: args.feature ? `Test Plan: ${args.feature}` : result.title,
      feature: args.feature || '',
      scope: args.scope || '',
      objectives: Array.isArray(args.objectives) ? args.objectives.join('; ') : '',
      status: 'draft',
    }),
  },
  {
    pattern: /generate_test_cases/,
    table: 'test_cases',
    idPrefix: 'tc',
    mapFields: (toolName, args, result) => ({
      title: `Test cases for ${args.feature}`,
      type: args.test_types ? (Array.isArray(args.test_types) ? args.test_types[0] : args.test_types) : 'functional',
      steps: JSON.stringify(result.test_cases || []),
      expected_result: 'Verify all tests pass',
      status: 'draft',
    }),
  },
  {
    pattern: /generate_bug_report/,
    table: 'bug_reports',
    idPrefix: 'br',
    mapFields: (toolName, args, result) => ({
      title: args.title || 'Bug Report',
      severity: args.severity || 'medium',
      priority: args.priority || 'medium',
      steps_to_reproduce: JSON.stringify(args.steps || []),
      expected: args.expected || '',
      actual: args.actual || '',
      environment: args.environment || 'dev',
      status: 'open',
    }),
  },
  {
    pattern: /generate_quality_gate/,
    table: 'quality_gates',
    idPrefix: 'qg',
    mapFields: (toolName, args, result) => ({
      name: args.gate_name || 'Quality Gate',
      criteria: Array.isArray(args.criteria) ? args.criteria.join('; ') : args.criteria || '',
      metrics: Array.isArray(args.metrics) ? args.metrics.join('; ') : args.metrics || '',
      status: 'active',
    }),
  },

  // SecZilla - Threat Modeling
  {
    pattern: /generate_threat_model/,
    table: 'threat_models',
    idPrefix: 'tm',
    mapFields: (toolName, args, result) => ({
      title: args.title || 'Threat Model',
      description: args.description || '',
      scope: args.system || 'system',
      status: 'draft',
    }),
  },
  {
    pattern: /generate_security_controls/,
    table: 'security_controls',
    idPrefix: 'sc',
    mapFields: (toolName, args, result) => ({
      title: args.control_name || 'Security Control',
      control_type: args.control_type || 'technical',
      status: 'active',
    }),
  },

  // ArchZilla - Architecture
  {
    pattern: /generate_solution_blueprint|generate_c4_diagram|generate_architecture/,
    table: 'architectures',
    idPrefix: 'arch',
    mapFields: (toolName, args, result) => ({
      title: args.architecture_name || `${toolName} Result`,
      description: args.description || '',
      version: '1.0',
      status: 'draft',
    }),
  },

  // Product/Business
  {
    pattern: /generate_epic|generate_feature_spec|generate_user_stories/,
    table: 'product_features',
    idPrefix: 'pf',
    mapFields: (toolName, args, result) => ({
      title: args.title || args.feature || `${toolName} Feature`,
      description: args.description || '',
      status: 'active',
    }),
  },

  // DevOps
  {
    pattern: /generate_release_plan|generate_deployment|create_deployment/,
    table: 'deployments',
    idPrefix: 'dep',
    mapFields: (toolName, args, result) => ({
      name: args.service_name || args.name || `Deployment`,
      environment: args.environment || 'staging',
      status: 'planned',
    }),
  },
];

export class ToolInterceptor {
  private pool: Pool;

  constructor(pool: Pool) {
    this.pool = pool;
  }

  /**
   * Intercept tool call and persist result to database
   */
  async intercept(
    toolName: string,
    args: Record<string, any>,
    result: any,
    mcp: string,
  ): Promise<void> {
    const rule = PERSISTENCE_RULES.find((r) => r.pattern.test(toolName));

    if (!rule) {
      return; // No persistence rule for this tool
    }

    try {
      const id = `${rule.idPrefix}_${uuidv4().slice(0, 12)}`;
      const now = new Date().toISOString();

      const data = {
        id,
        ...rule.mapFields(toolName, args, result),
        created_at: now,
        updated_at: now,
      };

      const keys = Object.keys(data);
      const values = Object.values(data);
      const placeholders = keys.map((_, i) => `$${i + 1}`).join(', ');

      const sql = `
        INSERT INTO ${rule.table} (${keys.join(', ')})
        VALUES (${placeholders})
        ON CONFLICT (id) DO NOTHING
      `;

      await this.pool.query(sql, values);
      console.log(`✅ [${mcp}] Persisted ${toolName} → ${rule.table}:${id}`);
    } catch (error) {
      console.error(`⚠️  [${mcp}] Failed to persist ${toolName}:`, error);
      // Don't fail the tool call if persistence fails
    }
  }
}
