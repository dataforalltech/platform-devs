"""Testes de Phase 2f — módulos que a migração ORM NÃO alterou:

  - ``ssh_key``: geração de keypair Ed25519 + round-trip Fernet (crypto puro).
  - ``TerraformProvisioner``: backend remoto + extra_tf_vars (subprocess mockado).

A integração store↔SSH-key (chave gerada em _start_provisioning, get_lease_ssh_key,
deleção ao terminar VM) é coberta no ``test_allocator_store.py`` (canônico, MySQL real)."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.db.provisioner import TerraformProvisioner
from src.db.ssh_key import (
    decrypt_private_key,
    encrypt_private_key,
    generate_fernet_key,
    generate_keypair,
)


# --------------------------------------------------------------------- #
# ssh_key module (crypto puro)                                          #
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
        apply_envs = [e for e in captured_envs if e]
        assert any(e.get("TF_VAR_ssh_public_key") == "ssh-ed25519 AAAA..." for e in apply_envs)

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
        assert 'backend "s3"' in override.read_text(encoding="utf-8")

    def test_destroy_workspace_skipped_when_not_listed(self, tmp_path):
        """Backend remoto: destroy sem workspace existente → on_done imediato."""
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()

        prov = TerraformProvisioner(backend_type="s3")
        done: list[bool] = []

        def fake_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "  default\n"  # workspace list não contém o vm_id
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
            time.sleep(0.3)  # destroy spawna thread

        assert done == [True]
