"""Testes de Phase 2f: SSH key per-VM + get_lease_ssh_key tool.

Cobre:
  - Geração de keypair Ed25519 (formato + unicidade).
  - Cifragem/decifragem Fernet round-trip.
  - AllocatorStore: keypair gerado em _start_provisioning.
  - AllocatorStore: get_lease_ssh_key retorna chave correta.
  - AllocatorStore: acesso negado por owner errado / status != ACTIVE.
  - AllocatorStore: chave deletada ao terminar VM (release + _on_vm_failed + GC).
  - extra_tf_vars com ssh_public_key passado ao provisioner.
  - get_lease_ssh_key tool function (camada tools/).
  - Backend remoto: _write_backend_override + workspace state isolation
    (subprocess mockado — sem terraform real).
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.knowledge.allocator_store import (
    AllocatorPolicy,
    AllocatorStore,
    AllocatorStoreError,
    LeaseNotFound,
)
from src.knowledge.provisioner import TerraformProvisioner
from src.knowledge.ssh_key import (
    decrypt_private_key,
    encrypt_private_key,
    generate_fernet_key,
    generate_keypair,
)
from src.models.allocator import VMRequest
from src.tools.allocator_tool import get_lease_ssh_key


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #
def _req(owner: str = "agent-x", spec: str = "cpu-small") -> VMRequest:
    return VMRequest(spec=spec, duration_min=60, owner=owner)


# --------------------------------------------------------------------- #
# ssh_key module                                                         #
# --------------------------------------------------------------------- #
class TestSSHKeyModule:
    def test_generate_keypair_returns_pem_and_openssh(self):
        pem, openssh = generate_keypair()
        assert pem.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert "ssh-ed25519" in openssh

    def test_keypairs_are_unique(self):
        k1 = generate_keypair()
        k2 = generate_keypair()
        assert k1[0] != k2[0]  # private keys differ
        assert k1[1] != k2[1]  # public keys differ

    def test_fernet_round_trip(self):
        fernet_key = generate_fernet_key()
        pem, _ = generate_keypair()
        encrypted = encrypt_private_key(pem, fernet_key)
        assert isinstance(encrypted, bytes)
        decrypted = decrypt_private_key(encrypted, fernet_key)
        assert decrypted == pem

    def test_wrong_fernet_key_raises(self):
        from cryptography.fernet import InvalidToken

        k1 = generate_fernet_key()
        k2 = generate_fernet_key()
        pem, _ = generate_keypair()
        encrypted = encrypt_private_key(pem, k1)
        with pytest.raises(InvalidToken):
            decrypt_private_key(encrypted, k2)

    def test_generate_fernet_key_length(self):
        import base64

        key = generate_fernet_key()
        raw = base64.urlsafe_b64decode(key)
        assert len(raw) == 32  # Fernet usa 32 bytes


# --------------------------------------------------------------------- #
# AllocatorStore — SSH key integration                                   #
# --------------------------------------------------------------------- #
class TestAllocatorSSHKeys:
    def _make_store(self, lease_secret: str | None = None) -> AllocatorStore:
        fk = generate_fernet_key().decode() if lease_secret is None else None
        return AllocatorStore(
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=lease_secret or (fk),
        )

    def test_vm_keys_row_created_on_provision(self):
        """_start_provisioning deve inserir em vm_keys."""
        store = self._make_store()
        d = store.request_vm(_req())
        vm_id = d.lease.vm_id
        row = store._con.execute(
            "SELECT vm_id, public_key FROM vm_keys WHERE vm_id=?", (vm_id,)
        ).fetchone()
        assert row is not None
        assert "ssh-ed25519" in row["public_key"]

    def test_get_lease_ssh_key_returns_pem(self):
        """get_lease_ssh_key retorna string PEM válida."""
        fernet_key = generate_fernet_key().decode()
        store = AllocatorStore(
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=fernet_key,
        )
        d = store.request_vm(_req(owner="agent-a"))
        assert d.lease.status == "ACTIVE"

        pem = store.get_lease_ssh_key(lease_id=d.lease.lease_id, owner="agent-a")
        assert pem.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")

    def test_get_lease_ssh_key_wrong_owner_raises(self):
        store = self._make_store()
        d = store.request_vm(_req(owner="agent-a"))
        with pytest.raises(AllocatorStoreError, match="owner"):
            store.get_lease_ssh_key(d.lease.lease_id, owner="agent-b")

    def test_get_lease_ssh_key_wrong_lease_id_raises(self):
        store = self._make_store()
        with pytest.raises(LeaseNotFound):
            store.get_lease_ssh_key("lease-nonexistent", owner="agent-x")

    def test_get_lease_ssh_key_not_available_before_active(self):
        """Lease em status != ACTIVE deve retornar erro."""
        class HoldProvisioner:
            """Provisioner que nunca chama on_ready — mantém lease PENDING."""
            def provision(self, spec, vm_id, modules_root, timeout_sec, on_ready, on_failed, extra_tf_vars=None):
                pass  # nunca chama on_ready

            def destroy(self, spec, vm_id, modules_root, timeout_sec, on_done, on_failed):
                on_done()

        store = AllocatorStore(
            provisioner=HoldProvisioner(),
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=generate_fernet_key().decode(),
        )
        d = store.request_vm(_req(owner="agent-x"))
        assert d.lease.status == "PENDING"

        with pytest.raises(AllocatorStoreError, match="PENDING"):
            store.get_lease_ssh_key(d.lease.lease_id, owner="agent-x")

    def test_ssh_key_deleted_after_last_lease_released(self):
        """release_lease (último) → vm_keys deve ser deletado."""
        store = self._make_store()
        d = store.request_vm(_req())
        vm_id = d.lease.vm_id

        # Confirma que chave existe
        assert store._con.execute(
            "SELECT 1 FROM vm_keys WHERE vm_id=?", (vm_id,)
        ).fetchone() is not None

        store.release_lease(d.lease.lease_id)

        # Chave deve ter sido deletada
        assert store._con.execute(
            "SELECT 1 FROM vm_keys WHERE vm_id=?", (vm_id,)
        ).fetchone() is None

    def test_ssh_key_deleted_on_provision_failure(self):
        """_on_vm_failed → vm_keys deletado."""
        class FailProv:
            def provision(self, spec, vm_id, modules_root, timeout_sec, on_ready, on_failed, extra_tf_vars=None):
                on_failed("simulated")

            def destroy(self, *a, on_done, **kw):
                on_done()

        store = AllocatorStore(
            provisioner=FailProv(),
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=generate_fernet_key().decode(),
        )
        d = store.request_vm(_req())
        vm_id = d.lease.vm_id

        # Após falha, chave deve ser deletada
        assert store._con.execute(
            "SELECT 1 FROM vm_keys WHERE vm_id=?", (vm_id,)
        ).fetchone() is None

    def test_ssh_key_deleted_on_gc_expired(self):
        """GC de leases expirados → VM órfã terminada → vm_keys deletado."""
        from datetime import timedelta

        from src.knowledge.allocator_store import _dt_to_str
        from src.models.allocator import now_utc

        store = self._make_store()
        d = store.request_vm(_req())
        vm_id = d.lease.vm_id

        # Expira lease no passado
        past = _dt_to_str(now_utc() - timedelta(hours=2))
        store._con.execute(
            "UPDATE leases SET expires_at=? WHERE lease_id=?",
            (past, d.lease.lease_id),
        )

        # Operação que dispara GC
        store.get_lease(d.lease.lease_id)

        assert store._con.execute(
            "SELECT 1 FROM vm_keys WHERE vm_id=?", (vm_id,)
        ).fetchone() is None

    def test_extra_tf_vars_has_ssh_public_key(self):
        """provisioner.provision() deve receber extra_tf_vars com ssh_public_key."""
        captured_vars: list[dict] = []

        class CapturingProvisioner:
            def provision(self, spec, vm_id, modules_root, timeout_sec, on_ready, on_failed, extra_tf_vars=None):
                captured_vars.append(extra_tf_vars or {})
                on_ready(f"cap://{vm_id}:22")

            def destroy(self, *a, on_done, **kw):
                on_done()

        store = AllocatorStore(
            provisioner=CapturingProvisioner(),
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=generate_fernet_key().decode(),
        )
        store.request_vm(_req())

        assert len(captured_vars) == 1
        assert "ssh_public_key" in captured_vars[0]
        assert captured_vars[0]["ssh_public_key"].startswith("ssh-ed25519")

    def test_shared_vm_reuses_existing_key(self):
        """Segunda lease em VM compartilhada: ambas têm acesso à mesma chave."""
        fk = generate_fernet_key().decode()
        store = AllocatorStore(
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=fk,
        )
        d1 = store.request_vm(_req(owner="a"))
        d2 = store.request_vm(_req(owner="b"))

        # Devem estar na mesma VM (compartilhamento)
        assert d1.lease.vm_id == d2.lease.vm_id

        pem1 = store.get_lease_ssh_key(d1.lease.lease_id, owner="a")
        pem2 = store.get_lease_ssh_key(d2.lease.lease_id, owner="b")
        # Mesma VM → mesma chave
        assert pem1 == pem2


# --------------------------------------------------------------------- #
# get_lease_ssh_key tool                                                 #
# --------------------------------------------------------------------- #
class TestGetLeaseSSHKeyTool:
    def _store(self) -> AllocatorStore:
        return AllocatorStore(
            policy=AllocatorPolicy(max_cost_usd_per_hour=20.0),
            lease_secret=generate_fernet_key().decode(),
        )

    def test_tool_returns_private_key_pem(self):
        store = self._store()
        d = store.request_vm(_req(owner="agent-t"))
        res = get_lease_ssh_key(store, lease_id=d.lease.lease_id, owner="agent-t")
        assert "private_key_pem" in res
        assert res["private_key_pem"].startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        assert res["key_type"] == "ed25519"
        assert "warning" in res

    def test_tool_error_on_wrong_owner(self):
        store = self._store()
        d = store.request_vm(_req(owner="owner-x"))
        res = get_lease_ssh_key(store, lease_id=d.lease.lease_id, owner="wrong-owner")
        assert res["error"] == "allocator_error"

    def test_tool_error_on_missing_lease(self):
        store = self._store()
        res = get_lease_ssh_key(store, lease_id="lease-not-exist", owner="x")
        assert res["error"] == "lease_not_found"

    def test_tool_error_on_empty_lease_id(self):
        store = self._store()
        res = get_lease_ssh_key(store, lease_id="", owner="x")
        assert res["error"] == "validation_error"

    def test_tool_error_on_empty_owner(self):
        store = self._store()
        d = store.request_vm(_req(owner="agent-y"))
        res = get_lease_ssh_key(store, lease_id=d.lease.lease_id, owner="")
        assert res["error"] == "validation_error"


# --------------------------------------------------------------------- #
# TerraformProvisioner — backend remoto + extra_tf_vars                 #
# --------------------------------------------------------------------- #
class TestTerraformProvisionerRemoteBackend:
    def test_extra_tf_vars_set_as_env(self, tmp_path):
        """extra_tf_vars deve ser convertido para TF_VAR_ no env do subprocess."""
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()
        (module_dir / ".terraform").mkdir()
        (module_dir / "states").mkdir()

        prov = TerraformProvisioner(terraform_bin="terraform")
        captured_envs: list[dict] = []

        def fake_run(cmd, **kwargs):
            captured_envs.append(kwargs.get("env") or {})
            r = MagicMock()
            r.returncode = 0
            r.stdout = '{"vm_ssh_endpoint": {"value": "1.2.3.4:22"}}'
            r.stderr = ""
            return r

        finished = threading.Event()
        results: list[str] = []

        with patch("subprocess.run", side_effect=fake_run):
            prov.provision(
                spec="cpu-small",
                vm_id="vm-env-test",
                modules_root=tmp_path,
                timeout_sec=30,
                on_ready=lambda hint: (results.append(hint), finished.set()),
                on_failed=lambda err: (results.append(f"FAIL:{err}"), finished.set()),
                extra_tf_vars={"ssh_public_key": "ssh-ed25519 AAAA..."},
            )
            finished.wait(timeout=5)

        assert results == ["1.2.3.4:22"]
        # Pelo menos um subprocess.run deve ter TF_VAR_ssh_public_key
        apply_envs = [e for e in captured_envs if e]
        assert any(
            e.get("TF_VAR_ssh_public_key") == "ssh-ed25519 AAAA..."
            for e in apply_envs
        )

    def test_backend_override_file_written_on_init(self, tmp_path):
        """Backend remoto: _backend_override.tf deve ser escrito no module dir."""
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()

        prov = TerraformProvisioner(
            terraform_bin="terraform",
            backend_type="s3",
            backend_config={"bucket": "my-tf-bucket", "region": "us-east-1"},
        )

        finished = threading.Event()

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            # init OK; workspace new → "already exists"; workspace select → OK
            # apply → OK; output → OK
            if "workspace" in cmd and "new" in cmd:
                r.returncode = 1
                r.stdout = "already exists"
                r.stderr = "Workspace already exists"
            elif "workspace" in cmd and "select" in cmd:
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
            elif "output" in cmd:
                r.returncode = 0
                r.stdout = '{"vm_ssh_endpoint": {"value": "10.0.0.1:22"}}'
                r.stderr = ""
            else:
                r.returncode = 0
                r.stdout = ""
                r.stderr = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            prov.provision(
                spec="cpu-small",
                vm_id="vm-ws-01",
                modules_root=tmp_path,
                timeout_sec=30,
                on_ready=lambda hint: finished.set(),
                on_failed=lambda err: finished.set(),
            )
            finished.wait(timeout=5)

        override = module_dir / "_backend_override.tf"
        assert override.exists()
        content = override.read_text(encoding="utf-8")
        assert 'backend "s3"' in content

    def test_destroy_workspace_skipped_when_not_listed(self, tmp_path):
        """Backend remoto: destroy sem workspace existente → on_done imediato."""
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()

        prov = TerraformProvisioner(backend_type="s3")
        done: list[bool] = []

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            # workspace list não contém o vm_id
            r.stdout = "  default\n"
            r.stderr = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            prov.destroy(
                spec="cpu-small",
                vm_id="vm-not-exist",
                modules_root=tmp_path,
                timeout_sec=10,
                on_done=lambda: done.append(True),
                on_failed=lambda err: done.append(False),
            )
            # destroy spawna thread — aguardar brevemente
            time.sleep(0.3)

        assert done == [True]
