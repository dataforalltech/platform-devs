#!/usr/bin/env python3
"""
Migração de dados Zilla: SQLite → PostgreSQL

Lê dados de arquivos .db SQLite em /tmp e insere no PostgreSQL.
Valida integridade e reporta estatísticas de migração.

Usage:
    python3 migrate_zillas_to_postgres.py [--validate] [--dry-run]
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
    'qazilla': Path('/tmp/qazilla.db'),
    'seczilla': Path('/tmp/seczilla.db'),
    'archzilla': Path('/tmp/archzilla.db'),
    'backzilla': Path('/tmp/backzilla.db'),
    'frontzilla': Path('/tmp/frontzilla.db'),
    'opszilla': Path('/tmp/opszilla.db'),
    'pozilla': Path('/tmp/pozilla.db'),
    'productzilla': Path('/tmp/productzilla.db'),
}

POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
    'database': os.getenv('POSTGRES_DB', 'app'),
}

# Mapeamento de tabelas: zilla -> [table_names]
ZILLA_TABLES = {
    'qazilla': ['test_plans', 'test_cases', 'test_scenarios', 'bug_reports',
                'quality_gates', 'test_results', 'checklists', 'qa_executions'],
    'seczilla': ['threat_models', 'vulnerabilities', 'security_controls', 'security_checklists'],
    'archzilla': ['architectures', 'arch_decisions', 'diagrams', 'reviews'],
    'backzilla': ['apis', 'back_services', 'back_integrations', 'back_workflows'],
    'frontzilla': ['front_features', 'components', 'design_tokens', 'front_workflows'],
    'opszilla': ['deployments', 'pipelines', 'infrastructure', 'incidents'],
    'pozilla': ['epics', 'po_features', 'po_stories', 'po_tasks'],
    'productzilla': ['product_features', 'user_stories', 'backlogs', 'releases'],
}

# ============================================================================
# Migration Logic
# ============================================================================

class ZillaMigrator:
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

    def migrate_zilla(self, zilla_name: str) -> bool:
        """Migrate a single Zilla from SQLite to PostgreSQL"""
        sqlite_path = SQLITE_PATHS.get(zilla_name)

        if not sqlite_path or not sqlite_path.exists():
            self.stats['warnings'].append(f"{zilla_name}: SQLite not found at {sqlite_path}")
            print(f"⚠️  {zilla_name}: SQLite not found at {sqlite_path}")
            return True  # Not an error - might not have data

        print(f"\n📊 Migrating {zilla_name}...")

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
                expected_tables = ZILLA_TABLES.get(zilla_name, [])
                if expected_tables and table_name not in expected_tables:
                    continue

                self._migrate_table(zilla_name, table_name, sqlite_cur)

            sqlite_conn.close()
            return True

        except Exception as e:
            error_msg = f"{zilla_name}: {str(e)}"
            self.stats['errors'].append(error_msg)
            print(f"❌ {error_msg}")
            return False

    def _migrate_table(self, zilla_name: str, table_name: str, sqlite_cur: sqlite3.Cursor):
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

        for zilla_name, tables in ZILLA_TABLES.items():
            print(f"\n{zilla_name}:")

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
    parser = argparse.ArgumentParser(description='Migrate Zilla data from SQLite to PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated without actual migration')
    parser.add_argument('--validate', action='store_true', help='Only validate existing migration, do not migrate')
    parser.add_argument('--zilla', help='Migrate only a specific Zilla (e.g., qazilla)')

    args = parser.parse_args()

    migrator = ZillaMigrator(dry_run=args.dry_run, validate_only=args.validate)

    try:
        if args.validate:
            migrator.validate_migration()
        else:
            # Migrate Zillas
            zillas_to_migrate = [args.zilla] if args.zilla else ZILLA_TABLES.keys()

            for zilla_name in zillas_to_migrate:
                migrator.migrate_zilla(zilla_name)

            # Validate migration
            migrator.validate_migration()

        migrator.report()

    finally:
        migrator.close()

if __name__ == '__main__':
    main()
