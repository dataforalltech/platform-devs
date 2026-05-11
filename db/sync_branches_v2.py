#!/usr/bin/env python3
"""
Sincroniza branches com tratamento robusto de erros de transação.
"""

import subprocess
import json
import psycopg2
import os

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

def sync_repo_branches(conn, repo_id, repo_name, branches):
    """Sincroniza branches de um repo com nova conexão por repo."""
    if not branches:
        return 0

    try:
        cur = conn.cursor()
        new_branches = 0

        for branch in branches:
            try:
                name = branch.get('name', '')
                commit_sha = branch.get('commit', {}).get('sha', '')[:12]
                commit_full = branch.get('commit', {}).get('sha', '')
                is_default = branch.get('protected', False) or name in ['main', 'master']

                cur.execute(
                    "SELECT id FROM repository_branches WHERE repository_id = %s AND branch_name = %s",
                    (repo_id, name)
                )
                exists = cur.fetchone()

                if not exists:
                    cur.execute("""
                        INSERT INTO repository_branches
                        (repository_id, branch_name, last_commit, last_commit_short, is_current, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    """, (repo_id, name, commit_full, commit_sha, is_default))
                    new_branches += 1
                else:
                    cur.execute("""
                        UPDATE repository_branches
                        SET last_commit = %s, last_commit_short = %s, updated_at = NOW()
                        WHERE repository_id = %s AND branch_name = %s
                    """, (commit_full, commit_sha, repo_id, name))

            except Exception as e:
                conn.rollback()
                cur = conn.cursor()

        conn.commit()
        return new_branches

    except Exception as e:
        conn.rollback()
        return 0

def main():
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cur = conn.cursor()

    # Pegar repos ativos
    cur.execute("SELECT id, name FROM repositories WHERE active = true ORDER BY name")
    repos = cur.fetchall()
    cur.close()

    print(f"\n{'='*80}")
    print(f"🌿 Sincronizando {len(repos)} repositórios com branches...")
    print(f"{'='*80}\n")

    total_new_branches = 0
    processed = 0

    for repo_id, repo_name in repos:
        branches = get_branches_via_gh(ORG, repo_name)
        if branches:
            new_count = sync_repo_branches(conn, repo_id, repo_name, branches)
            total_new_branches += new_count
            processed += 1
            print(f"  ✅ {repo_name:<50} ({len(branches)} branches, +{new_count} novos)")
        else:
            print(f"  ⏭️  {repo_name:<50} (sem branches ou erro)")

    conn.close()

    print(f"\n{'='*80}")
    print(f"✅ Sincronização concluída")
    print(f"   - {processed} repositórios processados")
    print(f"   - {total_new_branches} novos branches adicionados")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    main()
