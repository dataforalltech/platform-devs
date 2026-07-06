#!/usr/bin/env python3
"""
Migração de dados DevTeam: SQLite → PostgreSQL

Lê dados de arquivos .db SQLite em /tmp e insere no PostgreSQL.
Valida integridade e reporta estatísticas de migração.

Usage:
    python3 migrate_devteam_to_postgres.py [--validate] [--dry-run]
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import os
import sys
from pathlib import Path
from datetime import datetime
import argparse

# ============================================================================
# Configuration
# ============================================================================

SQLITE_PATHS = {
    'qa-engineer': Path('/tmp/qa-engineer.db'),
    'security': Path('/tmp/security.db'),
    'architecture': Path('/tmp/architecture.db'),
    'backend': Path('/tmp/backend.db'),
    'frontend': Path('/tmp/frontend.db'),
    'devops': Path('/tmp/devops.db'),
    'product-owner': Path('/tmp/product-owner.db'),
    'product-manager': Path('/tmp/product-manager.db'),
}

POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
    'database': os.getenv('POSTGRES_DB', 'app'),
}

# Mapeamento de tabelas: devteam -> [table_names]
DEVTEAM_TABLES = {
    'qa-engineer': ['test_plans', 'test_cases', 'test_scenarios', 'bug_reports',
                'quality_gates', 'test_results', 'checklists', 'qa_executions'],
    'security': ['threat_models', 'vulnerabilities', 'security_controls', 'security_checklists'],
    'architecture': ['architectures', 'arch_decisions', 'diagrams', 'reviews'],
    'backend': ['apis', 'back_services', 'back_integrations', 'back_workflows'],
    'frontend': ['front_features', 'components', 'design_tokens', 'front_workflows'],
    'devops': ['deployments', 'pipelines', 'infrastructure', 'incidents'],
    'product-owner': ['epics', 'po_features', 'po_stories', 'po_tasks'],
    'product-manager': ['product_features', 'user_stories', 'backlogs', 'releases'],
}

# ============================================================================
# Migration Logic
# ============================================================================

class DevTeamMigrator:
    def __init__(self, dry_run=False, validate_only=False):
        self.dry_run = dry_run
        self.validate_only = validate_only
        self.stats = {
            'tables_migrated': 0,
            'rows_migrated': 0,
            'errors': [],
            'warnings': [],
        }

        # Connect to PostgreSQL
        try:
            self.pg_conn = psycopg2.connect(**POSTGRES_CONFIG)
            self.pg_cur = self.pg_conn.cursor()
            print("✅ PostgreSQL connected")
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            sys.exit(1)

    def migrate_devteam(self, devteam_name: str) -> bool:
        """Migrate a single DevTeam from SQLite to PostgreSQL"""
        sqlite_path = SQLITE_PATHS.get(devteam_name)

        if not sqlite_path or not sqlite_path.exists():
            self.stats['warnings'].append(f"{devteam_name}: SQLite not found at {sqlite_path}")
            print(f"⚠️  {devteam_name}: SQLite not found at {sqlite_path}")
            return True  # Not an error - might not have data

        print(f"\n📊 Migrating {devteam_name}...")

        try:
            sqlite_conn = sqlite3.connect(str(sqlite_path))
            sqlite_conn.row_factory = sqlite3.Row
            sqlite_cur = sqlite_conn.cursor()

            # Get list of tables in SQLite
            sqlite_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            sqlite_tables = [row[0] for row in sqlite_cur.fetchall()]

            # Migrate each table
            for table_name in sqlite_tables:
                # Skip if not in expected list (might be internal SQLite tables)
                expected_tables = DEVTEAM_TABLES.get(devteam_name, [])
                if expected_tables and table_name not in expected_tables:
                    continue

                self._migrate_table(devteam_name, table_name, sqlite_cur)

            sqlite_conn.close()
            return True

        except Exception as e:
            error_msg = f"{devteam_name}: {str(e)}"
            self.stats['errors'].append(error_msg)
            print(f"❌ {error_msg}")
            return False

    def _migrate_table(self, devteam_name: str, table_name: str, sqlite_cur: sqlite3.Cursor):
        """Migrate a single table"""
        try:
            # Get data from SQLite
            sqlite_cur.execute(f"SELECT * FROM {table_name}")
            rows = sqlite_cur.fetchall()

            if not rows:
                print(f"   ℹ️  {table_name}: 0 rows")
                return

            # Get column names
            columns = [desc[0] for desc in sqlite_cur.description]

            # Prepare data for PostgreSQL
            # Handle JSONB columns (items, config, etc.)
            import json
            pg_rows = []
            for row in rows:
                pg_row = []
                for col_name, val in zip(columns, row):
                    # Convert JSON strings to proper format for JSONB
                    if col_name in ['items', 'config', 'content', 'spec', 'acceptance_criteria', 'steps', 'openapi_spec', 'diagram_type']:
                        if isinstance(val, str):
                            try:
                                val = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                pass  # Keep as string if not valid JSON
                        elif val is not None and not isinstance(val, (dict, list)):
                            pass  # Keep as is
                    pg_row.append(val)
                pg_rows.append(tuple(pg_row))

            if self.dry_run:
                print(f"   [DRY RUN] {table_name}: {len(pg_rows)} rows (would migrate)")
                return

            # Insert into PostgreSQL
            if pg_rows:
                placeholders = ','.join(['%s'] * len(columns))
                sql = f"""
                    INSERT INTO {table_name} ({', '.join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT (id) DO NOTHING
                """

                try:
                    execute_values(self.pg_cur, sql, pg_rows, page_size=1000)
                    self.pg_conn.commit()

                    self.stats['tables_migrated'] += 1
                    self.stats['rows_migrated'] += len(pg_rows)
                    print(f"   ✅ {table_name}: {len(pg_rows)} rows")

                except Exception as e:
                    self.pg_conn.rollback()
                    error_msg = f"{table_name}: {str(e)}"
                    self.stats['errors'].append(error_msg)
                    print(f"   ❌ {error_msg}")

        except Exception as e:
            error_msg = f"{table_name}: {str(e)}"
            self.stats['errors'].append(error_msg)
            print(f"   ❌ {error_msg}")

    def validate_migration(self):
        """Validate that migration was successful"""
        print("\n📋 Validating migration...")

        for devteam_name, tables in DEVTEAM_TABLES.items():
            print(f"\n{devteam_name}:")

            for table_name in tables:
                try:
                    self.pg_cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = self.pg_cur.fetchone()[0]

                    if count > 0:
                        print(f"   ✅ {table_name}: {count} rows")
                    else:
                        print(f"   ℹ️  {table_name}: 0 rows (empty)")

                except psycopg2.Error as e:
                    print(f"   ⚠️  {table_name}: {str(e)}")

    def report(self):
        """Print migration report"""
        print("\n" + "=" * 80)
        print("📊 MIGRATION REPORT")
        print("=" * 80)

        print(f"\n✅ Tables migrated: {self.stats['tables_migrated']}")
        print(f"✅ Rows migrated: {self.stats['rows_migrated']}")

        if self.stats['warnings']:
            print(f"\n⚠️  Warnings ({len(self.stats['warnings'])}):")
            for warning in self.stats['warnings']:
                print(f"   - {warning}")

        if self.stats['errors']:
            print(f"\n❌ Errors ({len(self.stats['errors'])}):")
            for error in self.stats['errors']:
                print(f"   - {error}")
        else:
            print(f"\n✅ No errors!")

        print("\n" + "=" * 80)

    def close(self):
        """Close database connections"""
        self.pg_conn.close()

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Migrate DevTeam data from SQLite to PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated without actual migration')
    parser.add_argument('--validate', action='store_true', help='Only validate existing migration, do not migrate')
    parser.add_argument('--devteam', help='Migrate only a specific DevTeam (e.g., qa-engineer)')

    args = parser.parse_args()

    migrator = DevTeamMigrator(dry_run=args.dry_run, validate_only=args.validate)

    try:
        if args.validate:
            migrator.validate_migration()
        else:
            # Migrate DevTeam
            devteam_to_migrate = [args.devteam] if args.devteam else DEVTEAM_TABLES.keys()

            for devteam_name in devteam_to_migrate:
                migrator.migrate_devteam(devteam_name)

            # Validate migration
            migrator.validate_migration()

        migrator.report()

    finally:
        migrator.close()

if __name__ == '__main__':
    main()
