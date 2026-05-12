"""Tool call interceptor - persists results to database automatically."""
import json
import re
import uuid
import asyncio
import sys
from typing import Any, Callable, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

def _debug_log(msg: str):
    """Write debug log to stderr and stdout."""
    print(msg, file=sys.stderr, flush=True)
    print(msg, file=sys.stdout, flush=True)

PERSISTENCE_RULES = {
    # QAZilla - Testing
    r'generate_test_plan': {
        'table': 'test_plans',
        'id_prefix': 'tp',
        'mapper': lambda tool, args, result: {
            'title': f"Test Plan: {args.get('feature', 'Test')}" if 'feature' in args else result.get('title', 'Test Plan'),
            'feature': args.get('feature', ''),
            'scope': args.get('scope', ''),
            'objectives': '; '.join(args.get('objectives', [])) if isinstance(args.get('objectives'), list) else '',
            'status': 'draft',
        }
    },
    r'generate_test_cases': {
        'table': 'test_cases',
        'id_prefix': 'tc',
        'mapper': lambda tool, args, result: {
            'title': f"Test cases for {args.get('feature', 'Feature')}",
            'type': args.get('test_types', ['functional'])[0] if isinstance(args.get('test_types'), list) else 'functional',
            'steps': json.dumps(result.get('test_cases', [])),
            'expected_result': 'Verify all tests pass',
            'status': 'draft',
        }
    },
    r'generate_bug_report': {
        'table': 'bug_reports',
        'id_prefix': 'br',
        'mapper': lambda tool, args, result: {
            'title': args.get('title', 'Bug Report'),
            'severity': args.get('severity', 'medium'),
            'priority': args.get('priority', 'medium'),
            'steps_to_reproduce': json.dumps(args.get('steps', [])),
            'expected': args.get('expected', ''),
            'actual': args.get('actual', ''),
            'environment': args.get('environment', 'dev'),
            'status': 'open',
        }
    },
    r'generate_quality_gate': {
        'table': 'quality_gates',
        'id_prefix': 'qg',
        'mapper': lambda tool, args, result: {
            'name': args.get('gate_name', 'Quality Gate'),
            'criteria': '; '.join(args.get('criteria', [])) if isinstance(args.get('criteria'), list) else '',
            'metrics': '; '.join(args.get('metrics', [])) if isinstance(args.get('metrics'), list) else '',
            'status': 'active',
        }
    },

    # SecZilla - Security
    r'generate_threat_model': {
        'table': 'threat_models',
        'id_prefix': 'tm',
        'mapper': lambda tool, args, result: {
            'title': args.get('title', 'Threat Model'),
            'description': args.get('description', ''),
            'scope': args.get('system', 'system'),
            'status': 'draft',
        }
    },
    r'generate_security_controls': {
        'table': 'security_controls',
        'id_prefix': 'sc',
        'mapper': lambda tool, args, result: {
            'title': args.get('control_name', 'Security Control'),
            'control_type': args.get('control_type', 'technical'),
            'status': 'active',
        }
    },

    # ArchZilla - Architecture
    r'(generate_solution_blueprint|generate_c4_diagram|generate_architecture)': {
        'table': 'architectures',
        'id_prefix': 'arch',
        'mapper': lambda tool, args, result: {
            'title': args.get('architecture_name', f'{tool} Result'),
            'description': args.get('description', ''),
            'version': '1.0',
            'status': 'draft',
        }
    },

    # Product/Business
    r'(generate_epic|generate_feature_spec|generate_user_stories)': {
        'table': 'product_features',
        'id_prefix': 'pf',
        'mapper': lambda tool, args, result: {
            'title': args.get('title') or args.get('feature') or f'{tool} Feature',
            'description': args.get('description', ''),
            'status': 'active',
        }
    },

    # DevOps
    r'(generate_release_plan|generate_deployment|create_deployment)': {
        'table': 'deployments',
        'id_prefix': 'dep',
        'mapper': lambda tool, args, result: {
            'name': args.get('service_name') or args.get('name') or 'Deployment',
            'environment': args.get('environment', 'staging'),
            'status': 'planned',
        }
    },

    # agent-twin-mcp - Identity & Context
    r'(authenticate|get_context|validate_token|whoami)': {
        'table': 'sessions',
        'id_prefix': 'sess',
        'mapper': lambda tool, args, result: {
            'user_id': result.get('user_id') or args.get('user_id', ''),
            'title': f"Session: {result.get('user_id', 'Unknown')}",
            'status': 'active',
        }
    },

    # config-mcp - Credentials & Configuration
    r'(set_secret|get_secret|list_secrets|set_config|get_config)': {
        'table': 'credentials',
        'id_prefix': 'cred',
        'mapper': lambda tool, args, result: {
            'credential_type': args.get('credential_type', tool.split('_')[0]),
            'namespace': args.get('namespace', 'default'),
            'status': 'active',
        }
    },

    # session-mcp - Sessions & Checkpoints
    r'(start_session|resume_session|save_checkpoint|list_sessions)': {
        'table': 'sessions',
        'id_prefix': 'sess',
        'mapper': lambda tool, args, result: {
            'user_id': args.get('user_id', result.get('user_id', '')),
            'title': args.get('title', result.get('title', 'Session')),
            'status': result.get('status', 'active'),
        }
    },

    # audit-mcp - Audit Logs
    r'(log_action|verify_decision|analyze_patterns)': {
        'table': 'audit_entries',
        'id_prefix': 'audit',
        'mapper': lambda tool, args, result: {
            'action': args.get('action', tool),
            'resource': args.get('resource', ''),
            'status': args.get('status', 'logged'),
        }
    },

    # infra-mcp - Infrastructure (Terraform, Policies, ADR)
    r'(apply_policy|create_infrastructure|validate_infrastructure|generate_adr)': {
        'table': 'infrastructure_resources',
        'id_prefix': 'infra',
        'mapper': lambda tool, args, result: {
            'resource_type': args.get('resource_type', tool.split('_')[0]),
            'name': args.get('name', result.get('name', 'Resource')),
            'status': args.get('status', 'created'),
        }
    },

    # services-mcp - Service Registry
    r'(register_service|update_service|list_services|check_health)': {
        'table': 'service_registrations',
        'id_prefix': 'svc',
        'mapper': lambda tool, args, result: {
            'service_name': args.get('service_name', args.get('name', 'Service')),
            'environment': args.get('environment', 'prod'),
            'status': result.get('status', 'registered'),
        }
    },

    # pipeline-mcp - CI/CD
    r'(trigger_pipeline|check_status|promote_build|rollback)': {
        'table': 'pipeline_executions',
        'id_prefix': 'pipe',
        'mapper': lambda tool, args, result: {
            'pipeline_name': args.get('pipeline_name', args.get('workflow', 'Pipeline')),
            'environment': args.get('environment', 'staging'),
            'status': result.get('status', args.get('status', 'triggered')),
        }
    },

    # qa-mcp - Quality Assurance
    r'(run_tests|lint_code|scan_security|check_coverage)': {
        'table': 'qa_results',
        'id_prefix': 'qa',
        'mapper': lambda tool, args, result: {
            'test_type': tool.split('_')[0] if '_' in tool else 'test',
            'component': args.get('component', args.get('path', 'unknown')),
            'status': result.get('status', 'completed'),
        }
    },

    # deploy-mcp - Git Operations (Commits, PRs, Branches)
    r'(create_commit|create_pr|merge_branch|tag_release)': {
        'table': 'git_operations',
        'id_prefix': 'git',
        'mapper': lambda tool, args, result: {
            'operation_type': tool.replace('create_', '').replace('_', ' ').title(),
            'branch': args.get('branch', result.get('branch', 'main')),
            'status': result.get('status', 'completed'),
        }
    },

    # test-mcp - Test Planning & Execution
    r'(create_test_plan|add_test_scenario|record_test_result)': {
        'table': 'test_executions',
        'id_prefix': 'test',
        'mapper': lambda tool, args, result: {
            'test_name': args.get('test_name', args.get('plan_name', 'Test')),
            'scenario': args.get('scenario', ''),
            'status': args.get('status', result.get('status', 'created')),
        }
    },

    # docs-mcp - Documentation
    r'(generate_doc|build_docs|publish_docs|audit_docs)': {
        'table': 'documentation',
        'id_prefix': 'doc',
        'mapper': lambda tool, args, result: {
            'doc_type': args.get('doc_type', args.get('type', 'general')),
            'title': args.get('title', result.get('title', 'Documentation')),
            'status': args.get('status', 'published'),
        }
    },

    # ai-governance-mcp - AI Policies & Governance
    r'(check_ai_policies|analyze_compliance|suggest_improvements|validate_model_behavior)': {
        'table': 'ai_policies',
        'id_prefix': 'aipol',
        'mapper': lambda tool, args, result: {
            'policy_name': args.get('policy_name', tool),
            'scope': args.get('scope', 'system'),
            'status': result.get('status', 'validated'),
        }
    },

    # auth-mcp - Authentication (Tokens, Sessions, JWT)
    r'(create_jwt|create_api_key|validate_token|refresh_token)': {
        'table': 'auth_tokens',
        'id_prefix': 'auth',
        'mapper': lambda tool, args, result: {
            'token_type': 'jwt' if 'jwt' in tool else 'api_key' if 'api_key' in tool else 'token',
            'user_id': args.get('user_id', result.get('user_id', '')),
            'status': 'active',
        }
    },

    # admin-mcp - Users & Roles
    r'(create_user|update_user|assign_role|list_users)': {
        'table': 'users_management',
        'id_prefix': 'user',
        'mapper': lambda tool, args, result: {
            'username': args.get('username', result.get('username', 'user')),
            'role': args.get('role', result.get('role', 'user')),
            'status': args.get('status', 'active'),
        }
    },

    # governance-mcp - Policies & Permissions
    r'(create_policy|enforce_rls|check_permission|analyze_permissions)': {
        'table': 'governance_policies',
        'id_prefix': 'gov',
        'mapper': lambda tool, args, result: {
            'policy_type': args.get('policy_type', tool.split('_')[0]),
            'resource': args.get('resource', '*'),
            'status': args.get('status', 'active'),
        }
    },

    # scheduler-mcp - Scheduled Tasks
    r'(create_task|schedule_job|trigger_workflow|get_task_status)': {
        'table': 'scheduled_tasks',
        'id_prefix': 'sch',
        'mapper': lambda tool, args, result: {
            'task_name': args.get('task_name', args.get('name', 'Task')),
            'schedule': args.get('cron', args.get('schedule', 'manual')),
            'status': result.get('status', args.get('status', 'scheduled')),
        }
    },

    # connectors-mcp - Data Connectors & Integrations
    r'(create_connector|test_connection|sync_data|validate_credentials)': {
        'table': 'connector_configs',
        'id_prefix': 'conn',
        'mapper': lambda tool, args, result: {
            'connector_type': args.get('connector_type', args.get('type', 'unknown')),
            'integration_name': args.get('integration_name', args.get('name', '')),
            'status': result.get('status', 'created'),
        }
    },

    # cache-mcp - Cache Operations
    r'(set_cache|get_cache|invalidate_cache|clear_cache)': {
        'table': 'cache_operations',
        'id_prefix': 'cache',
        'mapper': lambda tool, args, result: {
            'operation_type': tool.split('_')[0].title(),
            'key_pattern': args.get('key', args.get('pattern', '*')),
            'status': 'completed',
        }
    },
}


class ToolInterceptor:
    """Intercepts tool calls and persists results to database."""

    def __init__(self, db_conn: Any):
        self.db_conn = db_conn

    def find_rule(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Find persistence rule matching tool name."""
        for pattern, rule in PERSISTENCE_RULES.items():
            if re.search(pattern, tool_name):
                return rule
        return None

    async def intercept(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        mcp: str,
    ) -> None:
        """Intercept tool call and persist result."""
        _debug_log(f"🔍 Interceptor called for {tool_name} on {mcp}")
        rule = self.find_rule(tool_name)
        if not rule:
            _debug_log(f"⏭️  No persistence rule found for {tool_name}")
            return  # No rule for this tool

        try:
            record_id = f"{rule['id_prefix']}_{str(uuid.uuid4())[:12]}"
            _debug_log(f"📝 Record ID: {record_id} for table: {rule['table']}")

            # Map fields using rule mapper
            data = rule['mapper'](tool_name, args, result or {})
            data['id'] = record_id
            data['created_at'] = '::now()'  # PostgreSQL now() function
            data['updated_at'] = '::now()'
            _debug_log(f"📊 Mapped data: {data}")

            # Build INSERT query
            cols = list(data.keys())
            vals = list(data.values())

            placeholders = ', '.join(['%s'] * len(cols))
            col_list = ', '.join(cols)

            sql = f"""
                INSERT INTO {rule['table']} ({col_list})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING
            """
            _debug_log(f"🔄 SQL: {sql}")
            _debug_log(f"📦 Values: {vals}")

            # Handle special values
            processed_vals = []
            for v in vals:
                if v == '::now()':
                    processed_vals.append(None)  # Will use DEFAULT
                else:
                    processed_vals.append(v)

            # Run blocking DB operation in thread pool to avoid blocking event loop
            _debug_log(f"🧵 About to run asyncio.to_thread for {tool_name}...")
            await asyncio.to_thread(self._execute_insert, sql, processed_vals, mcp, tool_name, rule['table'], record_id)
            _debug_log(f"✅ asyncio.to_thread completed for {tool_name}")

        except Exception as error:
            _debug_log(f"⚠️  [{mcp}] Failed to persist {tool_name}: {error}")
            import traceback
            traceback.print_exc()
            # Don't fail the tool call if persistence fails

    def _execute_insert(self, sql: str, processed_vals: list, mcp: str, tool_name: str, table: str, record_id: str) -> None:
        """Execute blocking database insert operation."""
        try:
            _debug_log(f"🧵 Thread executing insert for {record_id}...")
            with self.db_conn.cursor() as cur:
                cur.execute(sql, processed_vals)
                self.db_conn.commit()
            _debug_log(f"✅ [{mcp}] Persisted {tool_name} → {table}:{record_id}")
        except Exception as error:
            _debug_log(f"⚠️  Thread failed to insert: {error}")
            import traceback
            traceback.print_exc()
            raise
