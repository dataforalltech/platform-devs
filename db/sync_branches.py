#!/usr/bin/env python3
"""
Sincroniza branches do GitHub para PostgreSQL de forma robusta.
"""

import subprocess
import json
import psycopg2
import os
from datetime import datetime

ORG = "dataforalltech"
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
    'database': os.getenv('POSTGRES_DB', 'app'),
}

def get_branches_via_gh(org, repo):
    """Obtém branches usando gh api."""
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/{org}/{repo}/branches', '--paginate'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        return []
    except:
        return []

def sync_all_branches():
    """Sincroniza branches para todos os repos ativos."""
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cur = conn.cursor()

    # Pegar todos os repos ativos
    cur.execute("SELECT id, name FROM repositories WHERE active = true ORDER BY name")
    repos = cur.fetchall()

    print(f"\n{'='*80}")
    print(f"🌿 Sincronizando {len(repos)} repositórios...")
    print(f"{'='*80}\n")

    total_branches = 0
    updated_repos = 0

    for repo_id, repo_name in repos:
        branches = get_branches_via_gh(ORG, repo_name)
        if not branches:
            print(f"  ⏭️  {repo_name:<50} (sem branches ou erro)")
            continue

        for branch in branches:
            try:
                name = branch.get('name', '')
                commit_sha = branch.get('commit', {}).get('sha', '')[:12]
                commit_full = branch.get('commit', {}).get('sha', '')
                is_default = branch.get('commit', {}).get('author', {}).get('name', '')

                # Verificar se existe
                cur.execute(
                    "SELECT id FROM repository_branches WHERE repository_id = %s AND branch_name = %s",
                    (repo_id, name)
                )
                exists = cur.fetchone()

                is_default_branch = branch.get('protected', False) or name in ['main', 'master']

                if exists:
                    cur.execute("""
                        UPDATE repository_branches
                        SET last_commit = %s, last_commit_short = %s, updated_at = NOW()
                        WHERE repository_id = %s AND branch_name = %s
                    """, (commit_full, commit_sha, repo_id, name))
                else:
                    cur.execute("""
                        INSERT INTO repository_branches
                        (repository_id, branch_name, last_commit, last_commit_short, is_current, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    """, (repo_id, name, commit_full, commit_sha, is_default_branch))
                    total_branches += 1

            except Exception as e:
                print(f"    ⚠️  {repo_name}/{branch.get('name')}: {e}")

        updated_repos += 1
        status = f"  ✅ {repo_name:<50} ({len(branches)} branches)"
        print(status)

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n{'='*80}")
    print(f"✅ {updated_repos} repositórios processados")
    print(f"✅ {total_branches} novos branches adicionados")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    sync_all_branches()
