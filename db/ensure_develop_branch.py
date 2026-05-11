#!/usr/bin/env python3
"""
Deploy-MCP Skill: Ensure Develop Branch
Cria/sincroniza branch develop em todos os repos.
Se não existir, cria a partir de main/master.

Usage:
    python3 ensure_develop_branch.py [--create] [--sync] [--all]
"""

import subprocess
import psycopg2
import os
import sys
from pathlib import Path

from repo_filters import get_automation_repos, POSTGRES_CONFIG, REPOS_DIR, ORG

# ============================================================================
# Configuration (canônico em repo_filters.py — ADR-002)
# ============================================================================

# ============================================================================
# Helper Functions
# ============================================================================

def get_active_repos():
    """Lista repos elegíveis para automação (active=true AND allows_automation=true)."""
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        repos = get_automation_repos(conn)
        conn.close()
        return repos
    except Exception as e:
        print(f"❌ Erro ao conectar PostgreSQL: {e}")
        return []

def repo_exists(repo_path):
    """Verifica se repo existe."""
    return (repo_path / '.git').exists()

def has_remote_branch(repo_path, branch):
    """Verifica se existe branch remota."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'rev-parse', f'origin/{branch}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except:
        return False

def get_default_branch(repo_path):
    """Obtém a branch default remota."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'symbolic-ref', 'refs/remotes/origin/HEAD'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            # Retorna algo como "refs/remotes/origin/main"
            branch = result.stdout.strip().split('/')[-1]
            return branch
        return None
    except:
        return None

def create_develop_from_main(repo_path):
    """Cria branch develop a partir de main/master."""
    try:
        # Fetch latest
        subprocess.run(
            ['git', '-C', str(repo_path), 'fetch', 'origin'],
            capture_output=True,
            text=True,
            timeout=30
        )

        # Tentar criar a partir de main ou master
        for source in ['main', 'master']:
            if has_remote_branch(repo_path, source):
                # Criar branch local baseada em origem
                result = subprocess.run(
                    ['git', '-C', str(repo_path), 'checkout', '-b', 'develop', f'origin/{source}'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    # Push para remoto
                    subprocess.run(
                        ['git', '-C', str(repo_path), 'push', '-u', 'origin', 'develop'],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    return True
                else:
                    # Tentar checkout se já existe localmente
                    subprocess.run(
                        ['git', '-C', str(repo_path), 'checkout', 'develop'],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    return True

        return False
    except:
        return False

def sync_develop(repo_path):
    """Sincroniza branch develop."""
    try:
        # Checkout develop
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'checkout', 'develop'],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return False

        # Pull
        subprocess.run(
            ['git', '-C', str(repo_path), 'pull', 'origin', 'develop', '--ff-only'],
            capture_output=True,
            text=True,
            timeout=30
        )

        return True
    except:
        return False

def get_last_commit(repo_path):
    """Obtém último commit."""
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_path), 'log', '-1', '--format=%h %s'],
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

def ensure_develop_branch(repos):
    """Garante que todos os repos tenham branch develop."""
    print(f"\n{'='*100}")
    print(f"🌿 CRIANDO/SINCRONIZANDO BRANCH 'develop'")
    print(f"{'='*100}\n")

    created = 0
    synced = 0
    failed = 0
    no_main = 0

    for repo in repos:
        if not repo_exists(repo['path']):
            print(f"   ⏭️  {repo['name']:<50} (não clonado)")
            continue

        # Verificar se já tem develop remota
        if has_remote_branch(repo['path'], 'develop'):
            # Sincronizar
            if sync_develop(repo['path']):
                last = get_last_commit(repo['path'])
                print(f"   ✅ {repo['name']:<50} (sync) ← {last[:40]}")
                synced += 1
            else:
                print(f"   ⚠️  {repo['name']:<50} (sync erro)")
                failed += 1
        else:
            # Criar develop a partir de main/master
            default = get_default_branch(repo['path'])
            if create_develop_from_main(repo['path']):
                if sync_develop(repo['path']):
                    last = get_last_commit(repo['path'])
                    print(f"   ✨ {repo['name']:<50} (criar+sync) ← {last[:40]}")
                    created += 1
                else:
                    print(f"   ⚠️  {repo['name']:<50} (criar ok, sync erro)")
                    failed += 1
            else:
                print(f"   ❌ {repo['name']:<50} (sem main/master)")
                no_main += 1

    print(f"\n   📊 Criados: {created}, Sincronizados: {synced}, Falhas: {failed}, Sem main: {no_main}\n")
    return created, synced, failed, no_main

def generate_final_report(repos):
    """Gera relatório final."""
    print(f"\n{'='*100}")
    print(f"📊 RELATÓRIO FINAL")
    print(f"{'='*100}\n")

    total = len(repos)
    cloned = sum(1 for r in repos if repo_exists(r['path']))
    with_develop = sum(1 for r in repos if repo_exists(r['path']) and has_remote_branch(r['path'], 'develop'))

    print(f"   📦 Total de repos ativos: {total}")
    print(f"   ✅ Clonados: {cloned}/{total} ({cloned*100//total}%)")
    print(f"   🌿 Com branch develop: {with_develop}/{total} ({with_develop*100//total}%)")

    print(f"\n{'='*100}\n")

    return with_develop == total

# ============================================================================
# Main
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Garantir branch develop em todos os repos')
    parser.add_argument('--create', action='store_true', help='Criar develop')
    parser.add_argument('--sync', action='store_true', help='Sincronizar develop')
    parser.add_argument('--report', action='store_true', help='Gerar relatório')
    parser.add_argument('--all', action='store_true', help='Tudo')

    args = parser.parse_args()

    if not any([args.create, args.sync, args.report, args.all]):
        args.create = True
        args.sync = True
        args.report = True

    repos = get_active_repos()
    if not repos:
        print("❌ Nenhum repo ativo encontrado")
        sys.exit(1)

    print(f"\n{'='*100}")
    print(f"🚀 ENSURE DEVELOP BRANCH")
    print(f"{'='*100}")
    print(f"📊 {len(repos)} repositórios para processar\n")

    if args.create or args.all:
        ensure_develop_branch(repos)

    if args.report or args.all:
        success = generate_final_report(repos)
        sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
