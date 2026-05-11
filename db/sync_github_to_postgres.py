#!/usr/bin/env python3
"""
GitHub → PostgreSQL Sync
Sincroniza repositórios e branches da organização para o banco de dados.

Usage:
    python3 sync_github_to_postgres.py [--org dataforalltech] [--full]
"""

import subprocess
import json
import psycopg2
from psycopg2.extras import execute_values
import os
import sys
from datetime import datetime
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

ORG = "dataforalltech"
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'claude-dev'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER', 'postgres'),
    'password': os.getenv('POSTGRES_PASSWORD', 'postgres_password_local_dev'),
    'database': os.getenv('POSTGRES_DB', 'app'),
}

# ============================================================================
# GitHub API via gh CLI
# ============================================================================

def gh_list_repos(org):
    """Lista todos os repositórios da organização."""
    try:
        result = subprocess.run(
            ['gh', 'repo', 'list', org, '--limit', '200', '--json',
             'name,url,description,primaryLanguage,isArchived,createdAt,updatedAt'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print(f"❌ Erro ao listar repos: {result.stderr}")
            return []
        return json.loads(result.stdout)
    except Exception as e:
        print(f"❌ Erro: {e}")
        return []

def gh_list_branches(org, repo):
    """Lista branches de um repositório."""
    try:
        result = subprocess.run(
            ['gh', 'repo', 'view', f'{org}/{repo}', '--json',
             'refs(nodes(name,target(oid,committedDate,message,author(name,email))))'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return []

        data = json.loads(result.stdout)
        branches = []
        if 'refs' in data and data['refs'] and 'nodes' in data['refs']:
            for ref in data['refs']['nodes']:
                branches.append({
                    'name': ref.get('name', ''),
                    'commit': ref['target'].get('oid', '')[:12],
                    'commit_full': ref['target'].get('oid', ''),
                    'date': ref['target'].get('committedDate', ''),
                    'author': ref['target'].get('author', {}).get('name', ''),
                    'email': ref['target'].get('author', {}).get('email', ''),
                })
        return branches
    except Exception as e:
        return []

# ============================================================================
# PostgreSQL Operations
# ============================================================================

def sync_repositories(conn, repos):
    """Sincroniza repositórios na tabela 'repositories'."""
    cur = conn.cursor()
    updated = 0
    created = 0

    # Pegar owner_id padrão (o primeiro usuário)
    cur.execute("SELECT id FROM users LIMIT 1")
    user_row = cur.fetchone()
    owner_id = user_row[0] if user_row else 1

    for repo in repos:
        try:
            # Verificar se existe
            cur.execute("SELECT id FROM repositories WHERE name = %s", (repo['name'],))
            existing = cur.fetchone()

            language = repo.get('primaryLanguage', {})
            lang_name = language.get('name') if isinstance(language, dict) else None

            if existing:
                # Atualizar
                cur.execute("""
                    UPDATE repositories
                    SET description = %s, language = %s, active = %s, updated_at = NOW(), last_sync_at = NOW()
                    WHERE name = %s
                """, (
                    repo.get('description'),
                    lang_name,
                    not repo.get('isArchived', False),
                    repo['name']
                ))
                updated += 1
            else:
                # Inserir
                cur.execute("""
                    INSERT INTO repositories
                    (name, url, owner_id, language, description, active, last_sync_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, NOW())
                """, (
                    repo['name'],
                    repo['url'],
                    owner_id,
                    lang_name,
                    repo.get('description'),
                    not repo.get('isArchived', False),
                    repo.get('createdAt', datetime.now().isoformat())
                ))
                created += 1
        except Exception as e:
            print(f"  ⚠️  Erro ao sync {repo['name']}: {e}")

    conn.commit()
    return created, updated

def sync_branches(conn, org):
    """Sincroniza branches para todos os repositórios."""
    cur = conn.cursor()

    # Pegar todos os repos
    cur.execute("SELECT id, name FROM repositories WHERE active = true AND allows_automation = true")
    repos = cur.fetchall()

    total_branches = 0
    updated_repos = 0

    for repo_id, repo_name in repos:
        branches = gh_list_branches(org, repo_name)
        if not branches:
            continue

        # Limpar branches antigos (opcional)
        # cur.execute("DELETE FROM repository_branches WHERE repository_id = %s", (repo_id,))

        for branch in branches:
            try:
                # Verificar se existe
                cur.execute(
                    "SELECT id FROM repository_branches WHERE repository_id = %s AND branch_name = %s",
                    (repo_id, branch['name'])
                )
                existing = cur.fetchone()

                # Determinar se é default
                is_default = branch['name'] in ['main', 'master']

                if existing:
                    cur.execute("""
                        UPDATE repository_branches
                        SET last_commit = %s, last_commit_short = %s, last_author = %s,
                            last_author_email = %s, last_commit_date = %s, updated_at = NOW()
                        WHERE repository_id = %s AND branch_name = %s
                    """, (
                        branch['commit_full'],
                        branch['commit'],
                        branch['author'],
                        branch['email'],
                        branch['date'] if branch['date'] else None,
                        repo_id,
                        branch['name']
                    ))
                else:
                    cur.execute("""
                        INSERT INTO repository_branches
                        (repository_id, branch_name, last_commit, last_commit_short,
                         last_author, last_author_email, last_commit_date, is_current, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """, (
                        repo_id,
                        branch['name'],
                        branch['commit_full'],
                        branch['commit'],
                        branch['author'],
                        branch['email'],
                        branch['date'] if branch['date'] else None,
                        is_default
                    ))
                    total_branches += 1
            except Exception as e:
                print(f"  ⚠️  Erro ao sync branch {repo_name}/{branch['name']}: {e}")

        updated_repos += 1

    conn.commit()
    return updated_repos, total_branches

# ============================================================================
# Main
# ============================================================================

def main():
    print(f"\n{'='*80}")
    print(f"🔄 GitHub → PostgreSQL Sync")
    print(f"{'='*80}\n")

    # Conectar ao PostgreSQL
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        print(f"✅ Conectado ao PostgreSQL em {POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}\n")
    except Exception as e:
        print(f"❌ Erro ao conectar PostgreSQL: {e}")
        sys.exit(1)

    # Etapa 1: Sincronizar Repositórios
    print(f"📦 Etapa 1: Sincronizando repositórios...")
    repos = gh_list_repos(ORG)
    if repos:
        created, updated = sync_repositories(conn, repos)
        print(f"   ✅ {created} novos repositórios criados")
        print(f"   ✅ {updated} repositórios atualizados")
        print(f"   📊 Total de repositórios: {len(repos)}\n")
    else:
        print(f"   ❌ Erro ao listar repositórios\n")

    # Etapa 2: Sincronizar Branches
    print(f"🌿 Etapa 2: Sincronizando branches...")
    updated_repos, new_branches = sync_branches(conn, ORG)
    print(f"   ✅ {updated_repos} repositórios processados")
    print(f"   ✅ {new_branches} novos branches adicionados\n")

    # Etapa 3: Estatísticas
    print(f"📊 Etapa 3: Estatísticas finais...")
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM repositories")
    total_repos = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM repository_branches")
    total_branches = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM repositories WHERE language IS NOT NULL")
    repos_with_lang = cur.fetchone()[0]

    print(f"   📦 Total de repositórios: {total_repos}")
    print(f"   🌿 Total de branches: {total_branches}")
    print(f"   💬 Repositórios com linguagem: {repos_with_lang}/{total_repos}")

    # Top 5 linguagens
    cur.execute("""
        SELECT language, COUNT(*) FROM repositories
        WHERE language IS NOT NULL
        GROUP BY language
        ORDER BY COUNT(*) DESC LIMIT 5
    """)
    print(f"\n   🏆 Top 5 linguagens:")
    for lang, count in cur.fetchall():
        print(f"      - {lang}: {count}")

    conn.close()
    print(f"\n✅ Sincronização concluída em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")

if __name__ == '__main__':
    main()
