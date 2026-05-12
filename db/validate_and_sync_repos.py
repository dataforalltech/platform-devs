#!/usr/bin/env python3
"""
Deploy-MCP Skill: Validação e Sincronização de Repositórios
Compara repos em 3 fontes: Filesystem, PostgreSQL, GitHub
E reconcilia discrepâncias.

Usage:
    python3 validate_and_sync_repos.py [--validate] [--sync] [--reconcile]
"""

import subprocess
import json
import psycopg2
import os
import sys
from pathlib import Path
from datetime import datetime

# ============================================================================
# Configuration
# ============================================================================

ORG = "dataforalltech"
REPOS_DIR = Path(os.getenv('PLATFORM_REPOS_DIR', os.path.expanduser('~/repos')))

POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
    'database': os.getenv('POSTGRES_DB', 'app'),
}

# ============================================================================
# Data Collection
# ============================================================================

def get_local_repos():
    """Lista repos do filesystem em ~/repos"""
    if not REPOS_DIR.exists():
        return {}

    repos = {}
    for path in REPOS_DIR.iterdir():
        if path.is_dir() and (path / '.git').exists():
            try:
                result = subprocess.run(
                    ['git', '-C', str(path), 'remote', 'get-url', 'origin'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                url = result.stdout.strip()
                repos[path.name] = {
                    'path': str(path),
                    'url': url,
                    'source': 'filesystem'
                }
            except:
                pass

    return repos

def get_db_repos():
    """Lista repos do PostgreSQL"""
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT name, url, language, active FROM repositories ORDER BY name")
        repos = {}
        for name, url, lang, active in cur.fetchall():
            repos[name] = {
                'url': url,
                'language': lang,
                'active': active,
                'source': 'database'
            }
        cur.close()
        conn.close()
        return repos
    except Exception as e:
        print(f"❌ Erro ao conectar PostgreSQL: {e}")
        return {}

def get_github_repos(org):
    """Lista repos do GitHub"""
    try:
        result = subprocess.run(
            ['gh', 'repo', 'list', org, '--limit', '200', '--json', 'name,url'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return {}

        repos = {}
        for repo in json.loads(result.stdout):
            repos[repo['name']] = {
                'url': repo['url'],
                'source': 'github'
            }
        return repos
    except Exception as e:
        print(f"⚠️  Erro ao listar GitHub: {e}")
        return {}

# ============================================================================
# Validation & Reconciliation
# ============================================================================

def validate_repositories():
    """Compara repos em 3 fontes e identifica discrepâncias."""
    print(f"\n{'='*100}")
    print(f"🔍 VALIDAÇÃO E SINCRONIZAÇÃO DE REPOSITÓRIOS")
    print(f"{'='*100}\n")

    local_repos = get_local_repos()
    db_repos = get_db_repos()
    github_repos = get_github_repos(ORG)

    print(f"📊 Contagem de repositórios:")
    print(f"   🖥️  Filesystem (~repos): {len(local_repos)}")
    print(f"   💾 PostgreSQL:           {len(db_repos)}")
    print(f"   🐙 GitHub ({ORG}):       {len(github_repos)}\n")

    all_names = set(local_repos.keys()) | set(db_repos.keys()) | set(github_repos.keys())

    missing_from_local = all_names - set(local_repos.keys())
    missing_from_db = all_names - set(db_repos.keys())
    missing_from_github = all_names - set(github_repos.keys())

    issues = []

    if missing_from_local:
        print(f"⚠️  FALTANDO NO FILESYSTEM ({len(missing_from_local)}):")
        for name in sorted(list(missing_from_local)[:10]):
            print(f"   ❌ {name:<45}")
        if len(missing_from_local) > 10:
            print(f"   ... e {len(missing_from_local)-10} mais")
        print()
        issues.extend([('missing_local', name) for name in missing_from_local])

    if missing_from_db:
        print(f"⚠️  FALTANDO NO BANCO ({len(missing_from_db)}):")
        for name in sorted(list(missing_from_db)[:10]):
            print(f"   ❌ {name:<45}")
        if len(missing_from_db) > 10:
            print(f"   ... e {len(missing_from_db)-10} mais")
        print()
        issues.extend([('missing_db', name) for name in missing_from_db])

    if missing_from_github:
        print(f"⚠️  FALTANDO NO GITHUB ({len(missing_from_github)}):")
        for name in sorted(missing_from_github):
            print(f"   ⚠️  {name:<45}")
        print()
        issues.extend([('missing_github', name) for name in missing_from_github])

    print(f"{'='*100}")
    if issues:
        print(f"🔴 ENCONTRADAS {len(issues)} DISCREPÂNCIAS")
    else:
        print(f"✅ TUDO SINCRONIZADO!")
    print(f"{'='*100}\n")

    return {
        'local': local_repos,
        'db': db_repos,
        'github': github_repos,
        'issues': issues,
        'stats': {
            'local_count': len(local_repos),
            'db_count': len(db_repos),
            'github_count': len(github_repos),
            'issue_count': len(issues),
        }
    }

def reconcile_repositories(validation_result):
    """Reconcilia discrepâncias entre as 3 fontes."""
    print(f"\n{'='*100}")
    print(f"🔧 RECONCILIAÇÃO")
    print(f"{'='*100}\n")

    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cur = conn.cursor()

    local_repos = validation_result['local']
    issues = validation_result['issues']

    reconciled = 0
    failed = 0

    for issue_type, repo_name in issues[:20]:
        try:
            if issue_type == 'only_local':
                local = local_repos.get(repo_name, {})
                cur.execute("""
                    INSERT INTO repositories (name, url, owner_id, active, last_sync_at, created_at, updated_at)
                    VALUES (%s, %s, 1, true, NOW(), NOW(), NOW())
                    ON CONFLICT (name) DO UPDATE SET updated_at = NOW()
                """, (repo_name, local.get('url', '')))
                conn.commit()
                print(f"   ✅ {repo_name:<45} adicionado ao banco")
                reconciled += 1
        except Exception as e:
            failed += 1

    conn.close()
    print(f"\n   Total: {reconciled} reconciliados, {failed} falharam\n")

# ============================================================================
# Main
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Validar e sincronizar repositórios')
    parser.add_argument('--validate', action='store_true', help='Validar discrepâncias')
    parser.add_argument('--reconcile', action='store_true', help='Reconciliar discrepâncias')
    parser.add_argument('--sync', action='store_true', help='Sincronizar com GitHub')
    parser.add_argument('--all', action='store_true', help='Validar + Reconciliar')

    args = parser.parse_args()

    if not any([args.validate, args.sync, args.reconcile, args.all]):
        args.validate = True

    result = validate_repositories()

    if args.reconcile or args.all:
        reconcile_repositories(result)

    sys.exit(0 if result['stats']['issue_count'] == 0 else 1)

if __name__ == '__main__':
    main()
