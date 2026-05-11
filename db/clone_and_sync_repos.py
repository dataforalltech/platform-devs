#!/usr/bin/env python3
"""
Deploy-MCP Skill: Clone and Sync Repositories
Garante que todos os repos não-arquivados estejam clonados em ~/repos
com a branch 'develop' atualizada localmente.

Usage:
    python3 clone_and_sync_repos.py [--clone] [--sync] [--prune] [--all]
"""

import subprocess
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
# Database Operations
# ============================================================================

def get_active_repos():
    """Lista repos não-arquivados do PostgreSQL."""
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, url, language
            FROM repositories
            WHERE active = true
            ORDER BY name
        """)
        repos = []
        for repo_id, name, url, language in cur.fetchall():
            repos.append({
                'id': repo_id,
                'name': name,
                'url': url,
                'language': language,
                'path': REPOS_DIR / name
            })
        cur.close()
        conn.close()
        return repos
    except Exception as e:
        print(f"❌ Erro ao conectar PostgreSQL: {e}")
        return []

def update_repo_status(repo_id, status, branch=None):
    """Atualiza status do repo no banco."""
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            UPDATE repositories
            SET last_sync_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """, (repo_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        pass

# ============================================================================
# Git Operations
# ============================================================================

def repo_exists(repo_path):
    """Verifica se repo existe e tem .git"""
    return (repo_path / '.git').exists()

def clone_repo(url, repo_path, repo_name):
    """Clona um repositório."""
    try:
        print(f"   📥 Clonando {repo_name}...", end="", flush=True)
        repo_path.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ['git', 'clone', '--depth', '5', url, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            print(f" ✅")
            return True
        else:
            print(f" ❌ {result.stderr[:50]}")
            return False
    except Exception as e:
        print(f" ❌ {str(e)[:50]}")
        return False

def has_branch(repo_path, branch):
    """Verifica se repo tem uma branch."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'rev-parse', f'--verify', f'origin/{branch}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except:
        return False

def get_current_branch(repo_path):
    """Obtém branch atual."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except:
        return None

def checkout_branch(repo_path, branch):
    """Faz checkout de uma branch."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'checkout', branch],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except:
        return False

def sync_branch(repo_path, branch):
    """Sincroniza uma branch (fetch + merge/rebase)."""
    try:
        # Fetch
        subprocess.run(
            ['git', '-C', str(repo_path), 'fetch', 'origin', branch],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Pull
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'pull', 'origin', branch, '--ff-only'],
            capture_output=True,
            text=True,
            timeout=30
        )

        return result.returncode == 0
    except:
        return False

def get_last_commit(repo_path, branch):
    """Obtém último commit da branch."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'log', '-1', '--format=%h %s', f'origin/{branch}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else "N/A"
    except:
        return "N/A"

# ============================================================================
# Main Operations
# ============================================================================

def clone_all_repos(repos):
    """Clona todos os repos não-clonados."""
    print(f"\n{'='*100}")
    print(f"📥 CLONANDO REPOSITÓRIOS NÃO-CLONADOS")
    print(f"{'='*100}\n")

    cloned = 0
    skipped = 0
    failed = 0

    for repo in repos:
        if repo_exists(repo['path']):
            print(f"   ⏭️  {repo['name']:<50} (já existe)")
            skipped += 1
        else:
            if clone_repo(repo['url'], repo['path'], repo['name']):
                cloned += 1
            else:
                failed += 1

    print(f"\n   📊 Clonados: {cloned}, Pulados: {skipped}, Falhados: {failed}\n")
    return cloned, skipped, failed

def sync_develop_branch(repos):
    """Sincroniza branch develop em todos os repos."""
    print(f"\n{'='*100}")
    print(f"🔄 SINCRONIZANDO BRANCH 'develop'")
    print(f"{'='*100}\n")

    synced = 0
    checkout_fail = 0
    no_branch = 0
    sync_fail = 0

    for repo in repos:
        if not repo_exists(repo['path']):
            print(f"   ⏭️  {repo['name']:<50} (não clonado)")
            continue

        # Verificar se tem branch develop
        if not has_branch(repo['path'], 'develop'):
            print(f"   ⚠️  {repo['name']:<50} (sem branch develop)")
            no_branch += 1
            continue

        # Fazer checkout
        if not checkout_branch(repo['path'], 'develop'):
            print(f"   ❌ {repo['name']:<50} (falha ao checkout)")
            checkout_fail += 1
            continue

        # Sincronizar
        if sync_branch(repo['path'], 'develop'):
            last_commit = get_last_commit(repo['path'], 'develop')
            print(f"   ✅ {repo['name']:<50} ← {last_commit[:40]}")
            synced += 1
            update_repo_status(repo['id'], 'synced', 'develop')
        else:
            print(f"   ⚠️  {repo['name']:<50} (sync com conflito)")
            sync_fail += 1

    print(f"\n   📊 Sincronizados: {synced}, Falha checkout: {checkout_fail}, Sem develop: {no_branch}, Conflito: {sync_fail}\n")
    return synced, checkout_fail, no_branch, sync_fail

def prune_branches(repos):
    """Remove branches locais não-rastreadas."""
    print(f"\n{'='*100}")
    print(f"🧹 LIMPANDO BRANCHES LOCAIS")
    print(f"{'='*100}\n")

    pruned = 0
    skipped = 0

    for repo in repos:
        if not repo_exists(repo['path']):
            continue

        try:
            result = subprocess.run(
                ['git', '-C', str(repo['path']), 'remote', 'prune', 'origin'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print(f"   ✅ {repo['name']:<50} (pruned)")
                pruned += 1
            else:
                skipped += 1
        except:
            skipped += 1

    print(f"\n   📊 Pruned: {pruned}, Skipped: {skipped}\n")
    return pruned, skipped

def generate_report(repos):
    """Gera relatório de status."""
    print(f"\n{'='*100}")
    print(f"📊 RELATÓRIO DE STATUS")
    print(f"{'='*100}\n")

    total = len(repos)
    cloned = sum(1 for r in repos if repo_exists(r['path']))
    has_develop = sum(1 for r in repos if repo_exists(r['path']) and has_branch(r['path'], 'develop'))

    print(f"   📦 Total de repos ativos: {total}")
    print(f"   ✅ Clonados localmente: {cloned}/{total} ({cloned*100//total}%)")
    print(f"   🌿 Com branch develop: {has_develop}/{total} ({has_develop*100//total}%)")

    # Top 10 repos
    print(f"\n   🏆 Últimos 10 sincronizados:\n")
    synced_repos = [r for r in repos if repo_exists(r['path']) and has_branch(r['path'], 'develop')]
    for i, repo in enumerate(synced_repos[-10:], 1):
        lang = repo['language'] or '-'
        print(f"      {i:2}. {repo['name']:<45} ({lang})")

    print(f"\n{'='*100}\n")

# ============================================================================
# Main
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Clonar e sincronizar repositórios')
    parser.add_argument('--clone', action='store_true', help='Clonar repos não-clonados')
    parser.add_argument('--sync', action='store_true', help='Sincronizar branch develop')
    parser.add_argument('--prune', action='store_true', help='Limpar branches remotas')
    parser.add_argument('--report', action='store_true', help='Gerar relatório')
    parser.add_argument('--all', action='store_true', help='Clone + Sync + Prune + Report')

    args = parser.parse_args()

    if not any([args.clone, args.sync, args.prune, args.report, args.all]):
        args.clone = True
        args.sync = True
        args.report = True

    # Obter repos do banco
    repos = get_active_repos()
    if not repos:
        print("❌ Nenhum repo ativo encontrado no banco")
        sys.exit(1)

    print(f"\n{'='*100}")
    print(f"🚀 CLONE & SYNC REPOSITORIES")
    print(f"{'='*100}")
    print(f"📊 {len(repos)} repositórios ativos para processar\n")

    # Executar operações
    if args.clone or args.all:
        clone_all_repos(repos)

    if args.sync or args.all:
        sync_develop_branch(repos)

    if args.prune or args.all:
        prune_branches(repos)

    if args.report or args.all:
        generate_report(repos)

    sys.exit(0)

if __name__ == '__main__':
    main()
