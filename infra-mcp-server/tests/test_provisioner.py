"""Testes do provisioner (Phase 2g).

Cobre:
  - ImmediateProvisioner: chama on_ready de forma síncrona.
  - TerraformProvisioner: chama on_failed quando modules_root é None.
  - TerraformProvisioner: chama on_failed quando spec dir não existe.
  - TerraformProvisioner: fluxo plan → infracost → apply com subprocess mockado.
  - TerraformProvisioner: cost check via infracost (cap excedido → on_failed).
  - TerraformProvisioner: infracost non-blocking (binary not found, timeout, parse error).
  - Integração allocator + provisioner assíncrono (AsyncMockProvisioner).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.knowledge.allocator_store import AllocatorPolicy, AllocatorStore
from src.knowledge.provisioner import (
    ImmediateProvisioner,
    OnDone,
    OnFailed,
    OnReady,
    TerraformProvisioner,
)
from src.models.allocator import VMRequest


def _req(owner: str = "agent-x", spec: str = "cpu-small", exclusive: bool = False) -> VMRequest:
    return VMRequest(spec=spec, duration_min=60, owner=owner, exclusive=exclusive)


# --------------------------------------------------------------------- #
# ImmediateProvisioner                                                   #
# --------------------------------------------------------------------- #
class TestImmediateProvisioner:
    def test_calls_on_ready_synchronously(self):
        prov = ImmediateProvisioner()
        result: list[str] = []
        prov.provision(
            spec="cpu-small",
            vm_id="vm-test",
            modules_root=None,
            timeout_sec=30,
            on_ready=lambda hint: result.append(hint),
            on_failed=lambda err: result.append(f"FAIL:{err}"),
        )
        assert len(result) == 1
        assert result[0] == "mock://vm-test:22"

    def test_on_failed_never_called(self):
        prov = ImmediateProvisioner()
        failed: list[str] = []
        prov.provision(
            spec="cpu-large",
            vm_id="vm-abc",
            modules_root=None,
            timeout_sec=30,
            on_ready=lambda hint: None,
            on_failed=lambda err: failed.append(err),
        )
        assert failed == []

    def test_hint_contains_vm_id(self):
        prov = ImmediateProvisioner()
        hints: list[str] = []
        prov.provision(
            spec="cpu-medium",
            vm_id="vm-12345",
            modules_root=None,
            timeout_sec=30,
            on_ready=lambda hint: hints.append(hint),
            on_failed=lambda err: None,
        )
        assert "vm-12345" in hints[0]


# --------------------------------------------------------------------- #
# TerraformProvisioner — fallback sem modules_root                      #
# --------------------------------------------------------------------- #
class TestTerraformProvisionerFallbacks:
    def test_fails_when_modules_root_none(self):
        prov = TerraformProvisioner()
        errors: list[str] = []
        prov.provision(
            spec="cpu-small",
            vm_id="vm-x",
            modules_root=None,
            timeout_sec=30,
            on_ready=lambda hint: None,
            on_failed=lambda err: errors.append(err),
        )
        assert len(errors) == 1
        assert "INFRA_TF_MODULES_ROOT" in errors[0]

    def test_fails_when_spec_dir_missing(self, tmp_path):
        prov = TerraformProvisioner()
        errors: list[str] = []
        # tmp_path existe mas não tem subdir cpu-small
        prov.provision(
            spec="cpu-small",
            vm_id="vm-y",
            modules_root=tmp_path,
            timeout_sec=30,
            on_ready=lambda hint: None,
            on_failed=lambda err: errors.append(err),
        )
        assert len(errors) == 1
        assert "cpu-small" in errors[0]


# --------------------------------------------------------------------- #
# TerraformProvisioner — subprocess mockado                             #
# --------------------------------------------------------------------- #
class TestTerraformProvisionerMocked:
    """Testa o fluxo plan → infracost → apply do TerraformProvisioner com subprocess mockado."""

    def _make_module_dir(self, tmp_path: Path) -> Path:
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()
        # Simula .terraform já inicializado (pula init)
        (module_dir / ".terraform").mkdir()
        return tmp_path

    def _ok(self, stdout: str = "") -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = stdout
        r.stderr = ""
        return r

    def _fail(self, stderr: str = "Error") -> MagicMock:
        r = MagicMock()
        r.returncode = 1
        r.stdout = ""
        r.stderr = stderr
        return r

    def test_happy_path_calls_on_ready(self, tmp_path):
        """Fluxo completo plan → apply → output → on_ready."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(terraform_bin="terraform")

        ready: list[str] = []
        failed: list[str] = []
        done = threading.Event()

        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.5:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-tftest",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: (ready.append(hint), done.set()),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert failed == [], f"Unexpected failure: {failed}"
        assert ready == ["10.0.0.5:22"]

    def test_plan_step_called_before_apply(self, tmp_path):
        """terraform plan deve ser chamado antes de apply."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(terraform_bin="terraform")

        calls: list[str] = []
        done = threading.Event()

        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.1:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                # cmd[1] é o subcomando terraform (plan, apply, output)
                calls.append(cmd[1] if len(cmd) > 1 else "?")
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-order",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: done.set(),
            )
            done.wait(timeout=5)

        # Deve ter chamado plan antes de apply
        assert "plan" in calls
        assert "apply" in calls
        plan_idx = calls.index("plan")
        apply_idx = calls.index("apply")
        assert plan_idx < apply_idx, f"plan deve vir antes de apply: {calls}"

    def test_plan_failure_calls_on_failed(self, tmp_path):
        """terraform plan falha → on_failed com 'plan falhou'."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(terraform_bin="terraform")

        failed: list[str] = []
        done = threading.Event()

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[1] == "plan":
                    return self._fail("Error: invalid config")
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-planfail",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert len(failed) == 1
        assert "plan falhou" in failed[0]

    def test_apply_failure_calls_on_failed(self, tmp_path):
        """terraform apply falha → on_failed com 'apply falhou'."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(terraform_bin="terraform")

        failed: list[str] = []
        done = threading.Event()

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if cmd[1] == "apply":
                    return self._fail("Error: something went wrong")
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-fail",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert len(failed) == 1
        assert "apply falhou" in failed[0]

    def test_missing_output_key_calls_on_failed(self, tmp_path):
        """terraform output sem 'vm_ssh_endpoint' → on_failed."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(terraform_bin="terraform")

        failed: list[str] = []
        done = threading.Event()

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "output" in cmd:
                    return self._ok('{"other_output": {"value": "x"}}')
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-nokey",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert len(failed) == 1
        assert "vm_ssh_endpoint" in failed[0]

    def test_plan_file_cleaned_up_after_success(self, tmp_path):
        """Plan file .tfplan é removido após apply bem-sucedido."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(terraform_bin="terraform")

        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.1:22"}}'

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = lambda cmd, **kw: (
                self._ok(output_json) if "output" in cmd else self._ok()
            )

            prov.provision(
                spec="cpu-small",
                vm_id="vm-cleanup",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: done.set(),
            )
            done.wait(timeout=5)

        # Plan file deve ser limpo após apply
        plan_file = modules_root / "cpu-small" / "vm-cleanup.tfplan"
        assert not plan_file.exists(), "Plan file deve ser removido após apply"


# --------------------------------------------------------------------- #
# AsyncMockProvisioner + AllocatorStore                                 #
# --------------------------------------------------------------------- #
class AsyncMockProvisioner:
    """Provisioner que simula delay real (usa thread como TerraformProvisioner)."""

    def __init__(self, delay_sec: float = 0.05, fail: bool = False) -> None:
        self._delay = delay_sec
        self._fail = fail

    def provision(
        self,
        spec: str,
        vm_id: str,
        modules_root,
        timeout_sec: int,
        on_ready: OnReady,
        on_failed: OnFailed,
        extra_tf_vars=None,
    ) -> None:
        def _run():
            time.sleep(self._delay)
            if self._fail:
                on_failed(f"mock failure for {vm_id}")
            else:
                on_ready(f"async-mock://{vm_id}:22")

        threading.Thread(target=_run, daemon=True).start()

    def destroy(
        self,
        spec: str,
        vm_id: str,
        modules_root,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        on_done()


class TestAllocatorWithAsyncProvisioner:
    """Verifica PENDING → ACTIVE lifecycle com provisioner assíncrono real."""

    def test_lease_starts_pending_then_active(self):
        """Com AsyncMockProvisioner, lease começa PENDING e vai ACTIVE após provisão."""
        prov = AsyncMockProvisioner(delay_sec=0.05)
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))

        decision = store.request_vm(_req())
        assert decision.outcome == "LEASED"
        lease_id = decision.lease.lease_id

        # Imediatamente após request: pode ser PENDING (thread não terminou)
        # ou ACTIVE (thread muito rápida) — ambos são válidos. Verificar ACTIVE eventualmente.
        deadline = time.monotonic() + 2.0
        final_lease = None
        while time.monotonic() < deadline:
            final_lease = store.get_lease(lease_id)
            if final_lease and final_lease.status == "ACTIVE":
                break
            time.sleep(0.01)

        assert final_lease is not None
        assert final_lease.status == "ACTIVE"
        assert final_lease.connection_hint == f"async-mock://{decision.lease.vm_id}:22"

    def test_pool_shows_ready_after_provisioning(self):
        """VM fica READY no pool depois de provisioner chamar on_ready."""
        prov = AsyncMockProvisioner(delay_sec=0.05)
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))
        store.request_vm(_req())

        # Aguarda VM virar READY
        deadline = time.monotonic() + 2.0
        pool = None
        while time.monotonic() < deadline:
            pool = store.list_pool()
            if pool.vms and pool.vms[0].status == "READY":
                break
            time.sleep(0.01)

        assert pool is not None
        assert len(pool.vms) == 1
        assert pool.vms[0].status == "READY"

    def test_failed_provision_expires_lease(self):
        """Quando provisioner falha, lease vira EXPIRED e VM vira TERMINATED."""
        prov = AsyncMockProvisioner(delay_sec=0.02, fail=True)
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))

        decision = store.request_vm(_req())
        lease_id = decision.lease.lease_id

        deadline = time.monotonic() + 2.0
        final_lease = None
        while time.monotonic() < deadline:
            final_lease = store.get_lease(lease_id)
            if final_lease and final_lease.status == "EXPIRED":
                break
            time.sleep(0.01)

        assert final_lease is not None
        assert final_lease.status == "EXPIRED"
        # Pool deve estar vazio (VM terminada)
        pool = store.list_pool()
        assert len(pool.vms) == 0

    def test_exclusive_lock_set_after_async_provision(self):
        """VM com lease exclusivo tem exclusive_locked_by correto após provisão."""
        prov = AsyncMockProvisioner(delay_sec=0.05)
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))

        d = store.request_vm(_req(exclusive=True))
        lease_id = d.lease.lease_id
        vm_id = d.lease.vm_id

        # Aguarda VM READY
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            pool = store.list_pool()
            if pool.vms and pool.vms[0].status == "READY":
                break
            time.sleep(0.01)

        pool = store.list_pool()
        assert len(pool.vms) == 1
        assert pool.vms[0].exclusive_locked_by == lease_id

        # Segunda request para a mesma VM deve ir para nova VM (exclusive lock ativo)
        d2 = store.request_vm(_req(owner="b"))
        assert d2.lease.vm_id != vm_id

    def test_immediate_provisioner_still_active(self):
        """ImmediateProvisioner (default) ainda funciona e lease fica ACTIVE imediatamente."""
        store = AllocatorStore(policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))
        d = store.request_vm(_req())
        assert d.outcome == "LEASED"
        assert d.lease.status == "ACTIVE"
        assert d.lease.connection_hint is not None


# --------------------------------------------------------------------- #
# ImmediateProvisioner — destroy                                         #
# --------------------------------------------------------------------- #
class TestImmediateProvisionerDestroy:
    def test_calls_on_done_synchronously(self):
        prov = ImmediateProvisioner()
        done: list[bool] = []
        prov.destroy(
            spec="cpu-small",
            vm_id="vm-test",
            modules_root=None,
            timeout_sec=30,
            on_done=lambda: done.append(True),
            on_failed=lambda err: done.append(False),
        )
        assert done == [True]

    def test_on_failed_never_called(self):
        prov = ImmediateProvisioner()
        failed: list[str] = []
        prov.destroy(
            spec="cpu-large",
            vm_id="vm-abc",
            modules_root=None,
            timeout_sec=30,
            on_done=lambda: None,
            on_failed=lambda err: failed.append(err),
        )
        assert failed == []


# --------------------------------------------------------------------- #
# TerraformProvisioner — destroy fallbacks                               #
# --------------------------------------------------------------------- #
class TestTerraformProvisionerDestroyFallbacks:
    def test_no_op_when_modules_root_none(self):
        """modules_root=None → on_done imediato (ImmediateProvisioner foi usado)."""
        prov = TerraformProvisioner()
        done: list[bool] = []
        prov.destroy(
            spec="cpu-small",
            vm_id="vm-x",
            modules_root=None,
            timeout_sec=30,
            on_done=lambda: done.append(True),
            on_failed=lambda err: done.append(False),
        )
        assert done == [True]

    def test_no_op_when_spec_dir_missing(self, tmp_path):
        """modules_root existe mas spec dir não → on_done imediato."""
        prov = TerraformProvisioner()
        done: list[bool] = []
        prov.destroy(
            spec="cpu-small",
            vm_id="vm-y",
            modules_root=tmp_path,  # tmp_path não tem cpu-small/
            timeout_sec=30,
            on_done=lambda: done.append(True),
            on_failed=lambda err: done.append(False),
        )
        assert done == [True]

    def test_no_op_when_state_file_missing(self, tmp_path):
        """State file ausente → on_done imediato (nada foi provisionado)."""
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()
        # states/ existe mas sem o state file da VM
        (module_dir / "states").mkdir()

        prov = TerraformProvisioner()
        done: list[bool] = []
        prov.destroy(
            spec="cpu-small",
            vm_id="vm-nostate",
            modules_root=tmp_path,
            timeout_sec=30,
            on_done=lambda: done.append(True),
            on_failed=lambda err: done.append(False),
        )
        assert done == [True]


# --------------------------------------------------------------------- #
# TerraformProvisioner — destroy com subprocess mockado                 #
# --------------------------------------------------------------------- #
class TestTerraformProvisionerDestroyMocked:
    def _make_module_with_state(self, tmp_path: Path, vm_id: str) -> Path:
        """Cria estrutura de módulo com state file para simular VM provisionada."""
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()
        (module_dir / ".terraform").mkdir()
        states_dir = module_dir / "states"
        states_dir.mkdir()
        # State file vazio mas existente (conteúdo não importa — subprocess é mockado)
        (states_dir / f"{vm_id}.tfstate").write_text("{}")
        return tmp_path

    def test_happy_path_calls_on_done(self, tmp_path):
        vm_id = "vm-destroy-ok"
        modules_root = self._make_module_with_state(tmp_path, vm_id)
        prov = TerraformProvisioner(terraform_bin="terraform")

        done: list[bool] = []
        failed: list[str] = []
        finished = threading.Event()

        with patch("subprocess.run") as mock_run:
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            r.stderr = ""
            mock_run.return_value = r

            prov.destroy(
                spec="cpu-small",
                vm_id=vm_id,
                modules_root=modules_root,
                timeout_sec=10,
                on_done=lambda: (done.append(True), finished.set()),
                on_failed=lambda err: (failed.append(err), finished.set()),
            )
            finished.wait(timeout=5)

        assert failed == [], f"Unexpected failure: {failed}"
        assert done == [True]
        # State file deve ser removido após destroy bem-sucedido
        assert not (modules_root / "cpu-small" / "states" / f"{vm_id}.tfstate").exists()

    def test_destroy_failure_calls_on_failed(self, tmp_path):
        vm_id = "vm-destroy-fail"
        modules_root = self._make_module_with_state(tmp_path, vm_id)
        prov = TerraformProvisioner(terraform_bin="terraform")

        failed: list[str] = []
        finished = threading.Event()

        with patch("subprocess.run") as mock_run:
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "Error: cannot destroy"
            mock_run.return_value = r

            prov.destroy(
                spec="cpu-small",
                vm_id=vm_id,
                modules_root=modules_root,
                timeout_sec=10,
                on_done=lambda: finished.set(),
                on_failed=lambda err: (failed.append(err), finished.set()),
            )
            finished.wait(timeout=5)

        assert len(failed) == 1
        assert "destroy falhou" in failed[0]
        # State file deve permanecer após falha (para retry manual)
        assert (modules_root / "cpu-small" / "states" / f"{vm_id}.tfstate").exists()


# --------------------------------------------------------------------- #
# Integração AllocatorStore + destroy                                   #
# --------------------------------------------------------------------- #
class RecordingProvisioner:
    """Provisioner que registra chamadas de provision e destroy para testes."""

    def __init__(self) -> None:
        self.provisions: list[str] = []
        self.destroys: list[str] = []

    def provision(
        self,
        spec: str,
        vm_id: str,
        modules_root,
        timeout_sec: int,
        on_ready: OnReady,
        on_failed: OnFailed,
        extra_tf_vars=None,
    ) -> None:
        self.provisions.append(vm_id)
        on_ready(f"rec://{vm_id}:22")

    def destroy(
        self,
        spec: str,
        vm_id: str,
        modules_root,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        self.destroys.append(vm_id)
        on_done()


class TestAllocatorDestroyIntegration:
    """Verifica que _schedule_destroy é chamado nos três pontos de trigger."""

    def test_destroy_called_when_last_lease_released(self):
        """Último lease liberado → VM terminada → destroy chamado."""
        prov = RecordingProvisioner()
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))
        d = store.request_vm(_req())
        assert d.outcome == "LEASED"
        vm_id = d.lease.vm_id

        store.release_lease(d.lease.lease_id)

        assert vm_id in prov.destroys

    def test_destroy_not_called_when_vm_still_shared(self):
        """Primeiro release de VM compartilhada não dispara destroy."""
        prov = RecordingProvisioner()
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))
        d1 = store.request_vm(_req(owner="a"))
        d2 = store.request_vm(_req(owner="b"))
        # Ambos devem ter a mesma VM (sharing)
        assert d1.lease.vm_id == d2.lease.vm_id
        vm_id = d1.lease.vm_id

        # Primeiro release: VM ainda tem lease de "b" → sem destroy
        store.release_lease(d1.lease.lease_id)
        assert vm_id not in prov.destroys

        # Segundo release: último lease → destroy
        store.release_lease(d2.lease.lease_id)
        assert vm_id in prov.destroys

    def test_destroy_called_on_provision_failure(self):
        """Provisão falha → _on_vm_failed → destroy chamado (idempotente se nada foi criado)."""
        class FailProvisioner:
            def __init__(self) -> None:
                self.destroys: list[str] = []

            def provision(self, spec, vm_id, modules_root, timeout_sec, on_ready, on_failed, extra_tf_vars=None) -> None:
                on_failed(f"simulated failure for {vm_id}")

            def destroy(self, spec, vm_id, modules_root, timeout_sec, on_done, on_failed) -> None:
                self.destroys.append(vm_id)
                on_done()

        prov = FailProvisioner()
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))
        d = store.request_vm(_req())

        assert d.outcome == "LEASED"  # LEASED com lease EXPIRED (provisão falhou)
        final = store.get_lease(d.lease.lease_id)
        assert final is None or final.status == "EXPIRED"
        assert d.lease.vm_id in prov.destroys

    def test_destroy_called_on_gc_expired(self):
        """Lease expirado por GC → VM órfã terminada → destroy chamado."""
        from datetime import timedelta

        from src.knowledge.allocator_store import _dt_to_str
        from src.models.allocator import now_utc

        prov = RecordingProvisioner()
        store = AllocatorStore(provisioner=prov, policy=AllocatorPolicy(max_cost_usd_per_hour=20.0))
        d = store.request_vm(_req())
        vm_id = d.lease.vm_id

        # Faz o lease expirar no passado
        past = _dt_to_str(now_utc() - timedelta(hours=2))
        store._con.execute("UPDATE leases SET expires_at=? WHERE lease_id=?", (past, d.lease.lease_id))

        # Qualquer operação dispara _gc_expired
        store.get_lease(d.lease.lease_id)

        assert vm_id in prov.destroys


# --------------------------------------------------------------------- #
# TerraformProvisioner — infracost cost check (Phase 2g)                #
# --------------------------------------------------------------------- #
class TestTerraformProvisionerInfracost:
    """Testa integração infracost no fluxo plan → cost-check → apply."""

    def _make_module_dir(self, tmp_path: Path) -> Path:
        module_dir = tmp_path / "cpu-small"
        module_dir.mkdir()
        (module_dir / ".terraform").mkdir()
        return tmp_path

    def _ok(self, stdout: str = "") -> MagicMock:
        r = MagicMock()
        r.returncode = 0
        r.stdout = stdout
        r.stderr = ""
        return r

    def _infracost_json(self, monthly: float) -> str:
        return f'{{"currency": "USD", "totalMonthlyCost": "{monthly:.4f}"}}'

    def test_no_cap_skips_infracost(self, tmp_path):
        """Sem cost_cap_usd_month configurado → infracost não é chamado."""
        modules_root = self._make_module_dir(tmp_path)
        # cap=None (default) → infracost skipped
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost",
            cost_cap_usd_month=None,
        )

        infracost_called = []
        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.1:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    infracost_called.append(True)
                    return self._ok(self._infracost_json(999.0))
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-nocap",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: done.set(),
            )
            done.wait(timeout=5)

        assert infracost_called == [], "infracost não deve ser chamado sem cost cap"

    def test_cap_not_exceeded_allows_provision(self, tmp_path):
        """infracost retorna custo abaixo do cap → provisão continua."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost",
            cost_cap_usd_month=200.0,
        )

        ready: list[str] = []
        failed: list[str] = []
        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.2:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    return self._ok(self._infracost_json(150.0))  # abaixo de 200
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-ok-cost",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: (ready.append(hint), done.set()),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert failed == [], f"Não deveria falhar: {failed}"
        assert ready == ["10.0.0.2:22"]

    def test_cap_exceeded_blocks_provision(self, tmp_path):
        """infracost retorna custo acima do cap → on_failed chamado, apply NÃO executado."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost",
            cost_cap_usd_month=100.0,
        )

        failed: list[str] = []
        apply_called = []
        done = threading.Event()

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    return self._ok(self._infracost_json(350.0))  # excede 100
                if cmd[1] == "apply":
                    apply_called.append(True)
                    return self._ok()
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-over-cap",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: done.set(),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert len(failed) == 1
        assert "350" in failed[0] or "excede" in failed[0], f"Msg esperada: {failed}"
        assert apply_called == [], "terraform apply NÃO deve ser chamado se custo excede cap"

    def test_infracost_binary_not_found_is_nonblocking(self, tmp_path):
        """infracost binary não encontrado → provisão continua (warning silencioso)."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost-notexist",
            cost_cap_usd_month=100.0,
        )

        ready: list[str] = []
        failed: list[str] = []
        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.3:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    raise FileNotFoundError("infracost-notexist: not found")
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-no-bin",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: (ready.append(hint), done.set()),
                on_failed=lambda err: (failed.append(err), done.set()),
            )
            done.wait(timeout=5)

        assert failed == [], f"FileNotFoundError deve ser non-blocking: {failed}"
        assert ready == ["10.0.0.3:22"]

    def test_infracost_timeout_is_nonblocking(self, tmp_path):
        """infracost timeout → provisão continua (non-blocking)."""
        import subprocess as _subprocess

        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost",
            cost_cap_usd_month=100.0,
        )

        ready: list[str] = []
        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.4:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    raise _subprocess.TimeoutExpired(cmd=cmd, timeout=120)
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-ic-timeout",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: (ready.append(hint), done.set()),
                on_failed=lambda err: done.set(),
            )
            done.wait(timeout=5)

        assert ready == ["10.0.0.4:22"]

    def test_infracost_parse_error_is_nonblocking(self, tmp_path):
        """JSON inválido do infracost → provisão continua (non-blocking)."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost",
            cost_cap_usd_month=100.0,
        )

        ready: list[str] = []
        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.5:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    return self._ok("not-valid-json{{{")
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-ic-parse",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: (ready.append(hint), done.set()),
                on_failed=lambda err: done.set(),
            )
            done.wait(timeout=5)

        assert ready == ["10.0.0.5:22"]

    def test_infracost_nonzero_exit_is_nonblocking(self, tmp_path):
        """infracost retorna nonzero → provisão continua (non-blocking)."""
        modules_root = self._make_module_dir(tmp_path)
        prov = TerraformProvisioner(
            terraform_bin="terraform",
            infracost_bin="infracost",
            cost_cap_usd_month=100.0,
        )

        ready: list[str] = []
        done = threading.Event()
        output_json = '{"vm_ssh_endpoint": {"value": "10.0.0.6:22"}}'

        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "infracost" in cmd[0]:
                    r = MagicMock()
                    r.returncode = 1
                    r.stdout = ""
                    r.stderr = "ERRO: falhou"
                    return r
                if "output" in cmd:
                    return self._ok(output_json)
                return self._ok()

            mock_run.side_effect = side_effect

            prov.provision(
                spec="cpu-small",
                vm_id="vm-ic-err",
                modules_root=modules_root,
                timeout_sec=10,
                on_ready=lambda hint: (ready.append(hint), done.set()),
                on_failed=lambda err: done.set(),
            )
            done.wait(timeout=5)

        assert ready == ["10.0.0.6:22"]
