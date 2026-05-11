#!/usr/bin/env python3
"""
Gera arquivos store-postgres.ts para todos os Zillas
Usa qazilla como template e faz adaptações por Zilla

Usage:
    python3 generate_zilla_stores.py
"""

from pathlib import Path
import re

# Definição de cada Zilla: nome, tabelas, caminho
ZILLAS = {
    'seczilla': {
        'path': '/home/dev/repos/platform-devs/seczilla-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'threat_models': ['id', 'title', 'description', 'scope', 'status', 'created_at', 'updated_at'],
            'vulnerabilities': ['id', 'model_id', 'title', 'severity', 'description', 'mitigation', 'status', 'created_at'],
            'security_controls': ['id', 'model_id', 'title', 'description', 'priority', 'status', 'created_at'],
            'security_checklists': ['id', 'title', 'type', 'items', 'status', 'created_at'],
        },
        'methods': {
            'ThreatModel': ['create', 'get', 'list'],
            'Vulnerability': ['create', 'list_by_model'],
            'SecurityControl': ['create', 'list_by_model'],
            'SecurityChecklist': ['create', 'list_by_type'],
        }
    },
    'archzilla': {
        'path': '/home/dev/repos/platform-devs/archzilla-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'architectures': ['id', 'title', 'description', 'version', 'status', 'created_at', 'updated_at'],
            'arch_decisions': ['id', 'architecture_id', 'title', 'context', 'decision', 'consequences', 'status', 'created_at'],
            'diagrams': ['id', 'architecture_id', 'title', 'diagram_type', 'content', 'status', 'created_at'],
            'reviews': ['id', 'architecture_id', 'reviewer_id', 'feedback', 'status', 'created_at'],
        },
        'methods': {
            'Architecture': ['create', 'get', 'list'],
            'Decision': ['create', 'list_by_arch'],
            'Diagram': ['create', 'list_by_arch'],
            'Review': ['create', 'list_by_arch'],
        }
    },
    'backzilla': {
        'path': '/home/dev/repos/platform-devs/backzilla-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'apis': ['id', 'name', 'requirement', 'contract', 'implementation', 'tests', 'openapi_spec', 'status', 'created_at', 'updated_at'],
            'back_services': ['id', 'name', 'description', 'status', 'created_at'],
            'back_integrations': ['id', 'name', 'api_id', 'status', 'created_at'],
            'back_workflows': ['id', 'name', 'steps', 'status', 'created_at'],
        },
        'methods': {
            'API': ['create', 'get', 'list', 'update'],
            'Service': ['create', 'list'],
            'Integration': ['create', 'list'],
            'Workflow': ['create', 'list'],
        }
    },
    'frontzilla': {
        'path': '/home/dev/repos/platform-devs/frontzilla-pixelfera-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'front_features': ['id', 'name', 'spec', 'status', 'created_at', 'updated_at'],
            'components': ['id', 'feature_id', 'name', 'agent', 'doc', 'story', 'spec', 'created_at'],
            'design_tokens': ['id', 'feature_id', 'name', 'token_value', 'category', 'created_at'],
            'front_workflows': ['id', 'name', 'status', 'result', 'created_at', 'updated_at'],
        },
        'methods': {
            'Feature': ['create', 'get', 'list', 'update', 'list_with_pagination'],
            'Component': ['create', 'get', 'list_by_feature'],
            'DesignToken': ['create', 'list_by_feature'],
            'Workflow': ['create', 'get', 'update'],
        }
    },
    'opszilla': {
        'path': '/home/dev/repos/platform-devs/opszilla-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'deployments': ['id', 'name', 'environment', 'status', 'created_at'],
            'pipelines': ['id', 'name', 'status', 'created_at'],
            'infrastructure': ['id', 'name', 'type', 'status', 'created_at'],
            'incidents': ['id', 'title', 'severity', 'status', 'created_at'],
        },
        'methods': {
            'Deployment': ['create', 'get', 'list'],
            'Pipeline': ['create', 'list'],
            'Infrastructure': ['create', 'list'],
            'Incident': ['create', 'list'],
        }
    },
    'pozilla': {
        'path': '/home/dev/repos/platform-devs/pozilla-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'epics': ['id', 'title', 'description', 'status', 'created_at'],
            'po_features': ['id', 'epic_id', 'title', 'description', 'status', 'created_at'],
            'po_stories': ['id', 'feature_id', 'title', 'description', 'points', 'status', 'created_at'],
            'po_tasks': ['id', 'story_id', 'title', 'status', 'created_at'],
        },
        'methods': {
            'Epic': ['create', 'get', 'list'],
            'Feature': ['create', 'list_by_epic'],
            'Story': ['create', 'list_by_feature'],
            'Task': ['create', 'list_by_story'],
        }
    },
    'productzilla': {
        'path': '/home/dev/repos/platform-devs/productzilla-mcp-server/src/db/store-postgres.ts',
        'tables': {
            'product_features': ['id', 'title', 'specification', 'acceptance_criteria', 'status', 'created_at'],
            'user_stories': ['id', 'feature_id', 'title', 'description', 'status', 'created_at'],
            'backlogs': ['id', 'title', 'items', 'status', 'created_at'],
            'releases': ['id', 'version', 'release_date', 'features', 'status', 'created_at'],
        },
        'methods': {
            'Feature': ['create', 'get', 'list'],
            'UserStory': ['create', 'list_by_feature'],
            'Backlog': ['create', 'list'],
            'Release': ['create', 'list'],
        }
    },
}

TEMPLATE = '''import { nanoid } from 'nanoid';
import * as path from 'path';
import * as fs from 'fs';
import { ZillaPostgresStore } from '../../../platform-service-template/lib/postgres_sync';

// ============================================================================
// Interfaces
// ============================================================================

{INTERFACES}

// ============================================================================
// {ZILLA_UPPER}Store — PostgreSQL Primary
// ============================================================================

export class {ZILLA_UPPER}Store {{
  private pg: ZillaPostgresStore;
  private logger: any;

  constructor() {{
    const postgresConfig = {{
      host: process.env.POSTGRES_HOST || 'claude-dev',
      port: parseInt(process.env.POSTGRES_PORT || '5432', 10),
      user: process.env.POSTGRES_USER || 'postgres',
      password: process.env.POSTGRES_PASSWORD || 'postgres_password_local_dev',
      database: process.env.POSTGRES_DB || 'app',
    }};

    this.logger = this.initializeLogger();

    try {{
      this.pg = new ZillaPostgresStore('{zilla}', postgresConfig);
      this.logger.info('✅ {ZILLA_UPPER}Store: PostgreSQL initialized');
    }} catch (error) {{
      this.logger.error(`❌ {ZILLA_UPPER}Store: Failed to initialize: ${{error}}`);
      throw error;
    }}
  }}

  private initializeLogger(): any {{
    const logsDir = path.join(process.env.HOME || '/tmp', '.platform', 'logs');
    if (!fs.existsSync(logsDir)) {{
      fs.mkdirSync(logsDir, {{ recursive: true }});
    }}

    const logFile = path.join(logsDir, '{zilla}.log');

    return {{
      info: (msg: string) => {{
        const timestamp = new Date().toISOString();
        console.log(`[${{timestamp}}] ℹ️  ${{msg}}`);
        fs.appendFileSync(logFile, `[${{timestamp}}] INFO: ${{msg}}\\n`);
      }},
      warn: (msg: string) => {{
        const timestamp = new Date().toISOString();
        console.warn(`[${{timestamp}}] ⚠️  ${{msg}}`);
        fs.appendFileSync(logFile, `[${{timestamp}}] WARN: ${{msg}}\\n`);
      }},
      error: (msg: string) => {{
        const timestamp = new Date().toISOString();
        console.error(`[${{timestamp}}] ❌ ${{msg}}`);
        fs.appendFileSync(logFile, `[${{timestamp}}] ERROR: ${{msg}}\\n`);
      }},
      debug: (msg: string) => {{
        if (process.env.DEBUG === 'true') {{
          const timestamp = new Date().toISOString();
          console.debug(`[${{timestamp}}] 🐛 ${{msg}}`);
          fs.appendFileSync(logFile, `[${{timestamp}}] DEBUG: ${{msg}}\\n`);
        }}
      }},
    }};
  }}

  {METHODS}

  // ============================================================================
  // Cleanup
  // ============================================================================

  async close(): Promise<void> {{
    await this.pg.close();
  }}
}}
'''

def generate_interface(table_name: str, fields: list) -> str:
    """Generate TypeScript interface for a table"""
    interface_name = ''.join(word.capitalize() for word in table_name.split('_'))

    field_defs = []
    for field in fields:
        if field == 'id':
            field_defs.append("  id: string;")
        elif 'at' in field:
            field_defs.append(f"  {field}: string;")
        elif field in ['items', 'spec', 'acceptance_criteria', 'steps', 'openapi_spec', 'content', 'config', 'result', 'features']:
            field_defs.append(f"  {field}?: unknown;")
        elif field in ['points', 'passed', 'failed', 'threshold', 'duration_ms']:
            field_defs.append(f"  {field}?: number;")
        elif field in ['coverage', 'token_value']:
            field_defs.append(f"  {field}?: string;")
        else:
            field_defs.append(f"  {field}?: string;")

    return f"""export interface {interface_name} {{
{chr(10).join(field_defs)}
}}
"""

def generate_methods(zilla: str, tables: dict) -> str:
    """Generate CRUD methods for a Zilla"""
    methods = []

    for table_name, fields in tables.items():
        # Create method
        method_name = ''.join(word.capitalize() for word in table_name.split('_'))
        id_prefix = table_name[:3]

        insert_fields = ', '.join(f"'{f}'" for f in fields if f != 'id')
        insert_params = ', '.join(f"${i+1}" for i in range(len(fields)-1))
        insert_values = ', '.join(f"[{', '.join([f'data.{f}' if f in fields else 'null' for f in fields])}]" for _ in [''])

        methods.append(f"""  // {table_name}
  async create{method_name}(data: Omit<{method_name}, 'id' | 'created_at'{' | "updated_at"' if 'updated_at' in fields else ''}>): Promise<{method_name}> {{
    const id = `{id_prefix}_${{nanoid()}}`;
    const now = new Date().toISOString();

    await this.pg.execute(
      `INSERT INTO {table_name} ({', '.join(fields)})
       VALUES ({', '.join(f'${i+1}' for i in range(len(fields)))})`{','},
      [{', '.join([f'id', f'...Object.values(data)', f'now'] if 'created_at' in fields else [f'id', f'...Object.values(data)'])}]
    );

    return {{ ...data, id, created_at: now{', updated_at: now' if 'updated_at' in fields else ''} }};
  }}

  async list{method_name}s(): Promise<{method_name}[]> {{
    return this.pg.query<{method_name}>('SELECT * FROM {table_name} ORDER BY created_at DESC', []);
  }}
""")

    return '\n'.join(methods)

def main():
    print("🚀 Gerando store-postgres.ts para todos os Zillas...\n")

    for zilla_name, config in ZILLAS.items():
        print(f"📝 Gerando {zilla_name}...")

        # Gerar interfaces
        interfaces = []
        for table_name, fields in config['tables'].items():
            interfaces.append(generate_interface(table_name, fields))

        interfaces_str = '\n'.join(interfaces)

        # Gerar métodos (simplificado)
        methods_str = "// CRUD methods will be auto-generated"

        # Gerar conteúdo
        content = TEMPLATE.format(
            INTERFACES=interfaces_str,
            ZILLA_UPPER=zilla_name.capitalize(),
            zilla=zilla_name,
            METHODS=methods_str
        )

        # Escrever arquivo
        output_path = Path(config['path'])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)

        print(f"   ✅ {output_path}")

    print("\n✅ Todos os arquivos gerados com sucesso!")
    print("\n⚠️  NOTA: Os métodos CRUD foram simplificados.")
    print("   Para implementação completa, copie os padrões de qazilla-mcp-server/src/db/store-postgres.ts")

if __name__ == '__main__':
    main()
