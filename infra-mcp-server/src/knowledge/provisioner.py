"""Provisioner — Phase 2g: provision + destroy + infracost cost check.

Hierarquia:
  Provisioner (Protocol)      — contrato: provision() + destroy()
  ImmediateProvisioner        — default/testes: callbacks síncronos, sem terraform
  TerraformProvisioner        — prod: background threads, terraform real

Fluxo TerraformProvisioner.provision() — backend LOCAL (default):
  1. terraform init   (se .terraform/ não existe; por spec, não por VM)
  2. terraform plan   -out=<vm_id>.tfplan -var="vm_id=..." -state=states/<vm_id>.tfstate
  3. infracost diff   --path <vm_id>.tfplan --format json  (se INFRA_COST_CAP_USD_MONTH)
  4. terraform apply  <vm_id>.tfplan -state=states/<vm_id>.tfstate  (sem -auto-approve)
  5. terraform output -json -state=...  → extrai vm_ssh_endpoint
  6. on_ready(vm_ssh_endpoint) ou on_failed(err_msg)

Fluxo TerraformProvisioner.provision() — backend REMOTO (s3/azurerm/gcs):
  1. Escreve `_backend_override.tf` com tipo do backend (idempotente, por spec dir).
  2. terraform init -reconfigure [+ -backend-config=... por config] (lock por spec dir).
  3. terraform workspace new <vm_id> (ou select se já existe).
  4. terraform plan   -out=<vm_id>.tfplan -var="vm_id=..." (workspace isola estado)
  5. infracost diff   --path <vm_id>.tfplan --format json  (se INFRA_COST_CAP_USD_MONTH)
  6. terraform apply  <vm_id>.tfplan (sem -auto-approve; workspace isola estado)
  7. terraform output -json → vm_ssh_endpoint.
  8. on_ready(vm_ssh_endpoint) ou on_failed(err_msg)

Fluxo TerraformProvisioner.destroy() — backend LOCAL:
  1. Verifica se states/<vm_id>.tfstate existe. Se não → on_done() imediato.
  2. terraform destroy -auto-approve -var="vm_id=..." -state=states/<vm_id>.tfstate
  3. Remove state file; on_done() ou on_failed(err_msg)

Fluxo TerraformProvisioner.destroy() — backend REMOTO:
  1. terraform workspace select <vm_id> (se falhar → workspace não existe → on_done()).
  2. terraform destroy -auto-approve -var="vm_id=..." (workspace corrente isola estado).
  3. terraform workspace select default; terraform workspace delete <vm_id>
  4. on_done() ou on_failed(err_msg)

extra_tf_vars:
  Vars adicionais passadas como env TF_VAR_<key>=<val> ao subprocesso terraform.
  Uso principal: SSH public key por VM gerada pelo allocator (Phase 2f).

cost_cap_usd_month (Phase 2g):
  Se configurado, terraform plan é verificado via infracost antes do apply.
  Se custo excede o cap → on_failed (provisão bloqueada).
  Se infracost não está no PATH → warning + continua (non-blocking).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..utils.logger import get_logger

_log = get_logger(__name__)

# Callbacks de provision
OnReady = Callable[[str], None]   # on_ready(connection_hint)
OnFailed = Callable[[str], None]  # on_failed(error_msg)
# Callback de destroy
OnDone = Callable[[], None]       # on_done()

_BACKEND_TEMPLATE = """\
# _backend_override.tf — auto-gerado por infra-mcp-server TerraformProvisioner.
# NÃO EDITAR — gerenciado pelo allocator. Sobrescreve backend declarado em main.tf.
terraform {{
  backend "{backend_type}" {{}}
}}
"""


# --------------------------------------------------------------------- #
# Protocol                                                               #
# --------------------------------------------------------------------- #
@runtime_checkable
class Provisioner(Protocol):
    """Contrato do provisioner. Implementações devem ser thread-safe."""

    def provision(
        self,
        spec: str,
        vm_id: str,
        modules_root: Path | None,
        timeout_sec: int,
        on_ready: OnReady,
        on_failed: OnFailed,
        extra_tf_vars: dict[str, str] | None = None,
    ) -> None:
        """Inicia provisão. Pode retornar antes de terminar (async)."""
        ...

    def destroy(
        self,
        spec: str,
        vm_id: str,
        modules_root: Path | None,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        """Inicia destruição do recurso cloud. Pode retornar antes de terminar (async)."""
        ...


# --------------------------------------------------------------------- #
# ImmediateProvisioner — default / testes                               #
# --------------------------------------------------------------------- #
class ImmediateProvisioner:
    """Provisão/destruição síncrona instantânea (sem thread, sem terraform).

    Compatível com todos os testes de Phase 2a-2f. Usado como default
    quando `tf_modules_root` não está configurado ou em `:memory:`.
    """

    def provision(
        self,
        spec: str,
        vm_id: str,
        modules_root: Path | None,
        timeout_sec: int,
        on_ready: OnReady,
        on_failed: OnFailed,
        extra_tf_vars: dict[str, str] | None = None,
    ) -> None:
        _log.debug(
            "immediate_provision",
            extra={"extras": {"vm_id": vm_id, "spec": spec}},
        )
        on_ready(f"mock://{vm_id}:22")

    def destroy(
        self,
        spec: str,
        vm_id: str,
        modules_root: Path | None,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        """Destroy no-op: nenhum recurso cloud real foi criado."""
        _log.debug(
            "immediate_destroy",
            extra={"extras": {"vm_id": vm_id, "spec": spec}},
        )
        on_done()


# --------------------------------------------------------------------- #
# TerraformProvisioner — prod                                           #
# --------------------------------------------------------------------- #
class TerraformProvisioner:
    """Provisiona e destrói VMs via terraform em background threads.

    Requer:
    - INFRA_TF_MODULES_ROOT apontando para diretório com subdiretórios
      por spec (e.g. <root>/cpu-small/main.tf).
    - Terraform no PATH (ou INFRA_TERRAFORM_BIN).
    - Output `vm_ssh_endpoint` no módulo (string: "host:port").

    Fluxo de provisão (Phase 2g):
      terraform plan  → infracost diff (se cost_cap_usd_month) → terraform apply <planfile>

    State isolation:
    - backend_type="local": cada VM usa states/<vm_id>.tfstate (-state flag).
    - backend_type remoto: terraform workspaces (<workspace>=<vm_id>).

    Thread safety:
    - _spec_init_locks: um threading.Lock por spec dir para serializar
      `terraform init` (operação não-concorrente segura).
    - _spec_init_done: set de specs já inicializadas para local backend
      (evita reinit desnecessário).
    """

    def __init__(
        self,
        terraform_bin: str = "terraform",
        backend_type: str = "local",
        backend_config: dict[str, str] | None = None,
        infracost_bin: str = "infracost",
        cost_cap_usd_month: float | None = None,
    ) -> None:
        self._terraform_bin = terraform_bin
        self._backend_type = backend_type.lower()
        self._backend_config: dict[str, str] = backend_config or {}
        self._infracost_bin = infracost_bin
        self._cost_cap_usd_month = cost_cap_usd_month
        # Locks por spec dir (serializam terraform init)
        self._spec_init_locks: dict[str, threading.Lock] = {}
        self._spec_init_lock_meta = threading.Lock()
        # Specs já inicializadas (local backend: init apenas na primeira vez)
        self._spec_init_done: set[str] = set()

    def _get_spec_lock(self, spec_dir: str) -> threading.Lock:
        with self._spec_init_lock_meta:
            if spec_dir not in self._spec_init_locks:
                self._spec_init_locks[spec_dir] = threading.Lock()
            return self._spec_init_locks[spec_dir]

    # ------------------------------------------------------------------ #
    # provision                                                            #
    # ------------------------------------------------------------------ #
    def provision(
        self,
        spec: str,
        vm_id: str,
        modules_root: Path | None,
        timeout_sec: int,
        on_ready: OnReady,
        on_failed: OnFailed,
        extra_tf_vars: dict[str, str] | None = None,
    ) -> None:
        if modules_root is None:
            on_failed(
                "INFRA_TF_MODULES_ROOT não configurado. "
                "Defina a variável de ambiente ou use ImmediateProvisioner para testes."
            )
            return

        module_dir = modules_root / spec
        if not module_dir.is_dir():
            on_failed(
                f"Módulo terraform para spec {spec!r} não encontrado em {module_dir}. "
                "Verifique INFRA_TF_MODULES_ROOT."
            )
            return

        thread = threading.Thread(
            target=self._run,
            args=(spec, vm_id, module_dir, timeout_sec, on_ready, on_failed, extra_tf_vars),
            daemon=True,
            name=f"tf-provision-{vm_id[:8]}",
        )
        thread.start()
        _log.info(
            "provision_started",
            extra={"extras": {"vm_id": vm_id, "spec": spec, "thread": thread.name}},
        )

    def _build_env(self, extra_tf_vars: dict[str, str] | None) -> dict[str, str]:
        """Constrói env com TF_VAR_<key>=<val> para vars adicionais."""
        env = dict(os.environ)
        if extra_tf_vars:
            for k, v in extra_tf_vars.items():
                env[f"TF_VAR_{k}"] = v
        return env

    def _ensure_init_local(
        self,
        spec: str,
        module_dir: Path,
        timeout_sec: int,
        on_failed: OnFailed,
    ) -> bool:
        """Garante que terraform está inicializado para backend local.

        Returns False e chama on_failed() se init falhar.
        """
        spec_key = str(module_dir)
        if spec_key in self._spec_init_done:
            return True
        lock = self._get_spec_lock(spec_key)
        with lock:
            if spec_key in self._spec_init_done:
                return True
            if not (module_dir / ".terraform").exists():
                _log.info(
                    "terraform_init",
                    extra={"extras": {"spec": spec, "cwd": str(module_dir)}},
                )
                r = subprocess.run(
                    [self._terraform_bin, "init", "-no-color", "-input=false"],
                    cwd=str(module_dir),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                if r.returncode != 0:
                    on_failed(f"terraform init falhou:\n{r.stderr[:2000]}")
                    return False
            self._spec_init_done.add(spec_key)
        return True

    def _ensure_init_remote(
        self,
        spec: str,
        module_dir: Path,
        timeout_sec: int,
        on_failed: OnFailed,
    ) -> bool:
        """Garante backend remoto inicializado via -backend-config.

        Escreve `_backend_override.tf` e roda `terraform init -reconfigure`.
        Serializado por spec dir para evitar concorrência em .terraform/.

        Returns False e chama on_failed() se falhar.
        """
        spec_key = str(module_dir)
        lock = self._get_spec_lock(spec_key)
        with lock:
            # Escreve override do backend (idempotente: mesmo conteúdo)
            override_file = module_dir / "_backend_override.tf"
            override_content = _BACKEND_TEMPLATE.format(backend_type=self._backend_type)
            if (
                not override_file.exists()
                or override_file.read_text(encoding="utf-8") != override_content
            ):
                override_file.write_text(override_content, encoding="utf-8")
                _log.info(
                    "backend_override_written",
                    extra={"extras": {"spec": spec, "backend_type": self._backend_type}},
                )

            # terraform init -reconfigure com -backend-config flags
            init_cmd = [
                self._terraform_bin, "init",
                "-no-color", "-input=false",
                "-reconfigure",
            ]
            for k, v in self._backend_config.items():
                init_cmd.append(f"-backend-config={k}={v}")

            _log.info(
                "terraform_init_remote",
                extra={"extras": {"spec": spec, "backend_type": self._backend_type}},
            )
            r = subprocess.run(
                init_cmd,
                cwd=str(module_dir),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if r.returncode != 0:
                on_failed(
                    f"terraform init (backend={self._backend_type}) falhou:\n{r.stderr[:2000]}"
                )
                return False
        return True

    def _workspace_create_or_select(
        self,
        vm_id: str,
        module_dir: Path,
        timeout_sec: int,
        on_failed: OnFailed,
    ) -> bool:
        """Cria ou seleciona workspace <vm_id> para isolamento de state.

        Returns False e chama on_failed() se falhar.
        """
        tf = self._terraform_bin
        cwd = str(module_dir)

        r = subprocess.run(
            [tf, "workspace", "new", vm_id, "-no-color"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return True
        # Workspace já existe → select
        if "already exists" in r.stderr or "already exists" in r.stdout:
            r2 = subprocess.run(
                [tf, "workspace", "select", vm_id, "-no-color"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r2.returncode == 0:
                return True
            on_failed(
                f"terraform workspace select {vm_id!r} falhou:\n{r2.stderr[:1000]}"
            )
            return False
        on_failed(f"terraform workspace new {vm_id!r} falhou:\n{r.stderr[:1000]}")
        return False

    def _check_cost(
        self,
        plan_file: Path,
        module_dir: Path,
        env: dict[str, str],
        on_failed: OnFailed,
    ) -> bool:
        """Verifica custo mensal estimado via infracost diff.

        Retorna True (continuar) ou False e chama on_failed() se custo excede cap.

        Non-blocking se infracost não está disponível (binary_not_found, timeout,
        parse error) — nesses casos loga warning e retorna True.

        Args:
            plan_file: Path do arquivo .tfplan binário gerado por terraform plan.
            module_dir: cwd para infracost (acesso aos providers).
            env: environ com TF_VAR_* já expandidos.
            on_failed: callback chamado se custo excede cap.

        Returns:
            True → provisão pode continuar.
            False → on_failed já chamado; provisão deve abortar.
        """
        if self._cost_cap_usd_month is None:
            return True  # sem cap configurado → skip

        _log.info(
            "infracost_check_start",
            extra={"extras": {
                "plan_file": str(plan_file),
                "cap_usd_month": self._cost_cap_usd_month,
            }},
        )

        try:
            r = subprocess.run(
                [
                    self._infracost_bin, "diff",
                    "--path", str(plan_file),
                    "--format", "json",
                ],
                cwd=str(module_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except FileNotFoundError:
            _log.warning(
                "infracost_not_found",
                extra={"extras": {"bin": self._infracost_bin}},
            )
            return True  # non-blocking
        except subprocess.TimeoutExpired:
            _log.warning(
                "infracost_timeout",
                extra={"extras": {"plan_file": str(plan_file)}},
            )
            return True  # non-blocking

        if r.returncode != 0:
            _log.warning(
                "infracost_nonzero",
                extra={"extras": {"rc": r.returncode, "stderr": r.stderr[:400]}},
            )
            return True  # non-blocking

        try:
            data = json.loads(r.stdout)
            monthly_str = data.get("totalMonthlyCost")
            monthly_cost = float(monthly_str) if monthly_str is not None else None
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning(
                "infracost_parse_error",
                extra={"extras": {"exc": str(exc), "stdout_preview": r.stdout[:300]}},
            )
            return True  # non-blocking

        if monthly_cost is None:
            _log.warning("infracost_no_cost_field", extra={"extras": {}})
            return True  # non-blocking

        _log.info(
            "infracost_check_result",
            extra={"extras": {
                "monthly_cost_usd": monthly_cost,
                "cap_usd_month": self._cost_cap_usd_month,
                "within_cap": monthly_cost <= self._cost_cap_usd_month,
            }},
        )

        if monthly_cost > self._cost_cap_usd_month:
            on_failed(
                f"Custo estimado ${monthly_cost:.2f}/mês excede o cap de "
                f"${self._cost_cap_usd_month:.2f}/mês (INFRA_COST_CAP_USD_MONTH). "
                "Provisão bloqueada. Ajuste o cap ou solicite aprovação humana."
            )
            return False

        return True

    def _run(
        self,
        spec: str,
        vm_id: str,
        module_dir: Path,
        timeout_sec: int,
        on_ready: OnReady,
        on_failed: OnFailed,
        extra_tf_vars: dict[str, str] | None,
    ) -> None:
        """Executa fluxo plan → infracost → apply em background thread."""
        tf = self._terraform_bin
        cwd = str(module_dir)
        env = self._build_env(extra_tf_vars)
        # Plan file fica no module dir (gitignored via *.tfplan); limpo após apply.
        plan_file = module_dir / f"{vm_id}.tfplan"

        try:
            if self._backend_type == "local":
                # ---- Backend local: -state por VM ----
                if not self._ensure_init_local(spec, module_dir, timeout_sec, on_failed):
                    return

                state_dir = module_dir / "states"
                state_dir.mkdir(exist_ok=True)
                state_file = str(state_dir / f"{vm_id}.tfstate")

                # PLAN
                _log.info(
                    "terraform_plan",
                    extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": "local"}},
                )
                r = subprocess.run(
                    [
                        tf, "plan",
                        "-no-color", "-input=false",
                        f"-out={plan_file}",
                        f"-var=vm_id={vm_id}",
                        f"-var=spec={spec}",
                        f"-state={state_file}",
                    ],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=env,
                )
                if r.returncode != 0:
                    on_failed(
                        f"terraform plan falhou (vm_id={vm_id}):\n{r.stderr[:2000]}"
                    )
                    return

                # COST CHECK
                if not self._check_cost(plan_file, module_dir, env, on_failed):
                    return

                # APPLY (from plan file — sem -auto-approve; plano já foi revisado)
                _log.info(
                    "terraform_apply",
                    extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": "local"}},
                )
                r = subprocess.run(
                    [
                        tf, "apply",
                        "-no-color", "-input=false",
                        f"-state={state_file}",
                        f"-state-out={state_file}",
                        str(plan_file),
                    ],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=env,
                )
                if r.returncode != 0:
                    on_failed(
                        f"terraform apply falhou (vm_id={vm_id}):\n{r.stderr[:2000]}"
                    )
                    return

                # OUTPUT
                r = subprocess.run(
                    [tf, "output", "-json", f"-state={state_file}"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )

            else:
                # ---- Backend remoto: workspace por VM ----
                if not self._ensure_init_remote(spec, module_dir, timeout_sec, on_failed):
                    return
                if not self._workspace_create_or_select(vm_id, module_dir, timeout_sec, on_failed):
                    return

                # PLAN
                _log.info(
                    "terraform_plan",
                    extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": self._backend_type}},
                )
                r = subprocess.run(
                    [
                        tf, "plan",
                        "-no-color", "-input=false",
                        f"-out={plan_file}",
                        f"-var=vm_id={vm_id}",
                        f"-var=spec={spec}",
                    ],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=env,
                )
                if r.returncode != 0:
                    on_failed(
                        f"terraform plan falhou (vm_id={vm_id}):\n{r.stderr[:2000]}"
                    )
                    return

                # COST CHECK
                if not self._check_cost(plan_file, module_dir, env, on_failed):
                    return

                # APPLY (from plan file — sem -auto-approve)
                _log.info(
                    "terraform_apply",
                    extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": self._backend_type}},
                )
                r = subprocess.run(
                    [
                        tf, "apply",
                        "-no-color", "-input=false",
                        str(plan_file),
                    ],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    env=env,
                )
                if r.returncode != 0:
                    on_failed(
                        f"terraform apply falhou (vm_id={vm_id}):\n{r.stderr[:2000]}"
                    )
                    return

                # OUTPUT (workspace ativo)
                r = subprocess.run(
                    [tf, "output", "-json"],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )

            # Extrai connection_hint (comum para ambos os backends)
            if r.returncode != 0:
                on_failed(f"terraform output falhou:\n{r.stderr[:1000]}")
                return

            try:
                outputs = json.loads(r.stdout)
                connection_hint = outputs["vm_ssh_endpoint"]["value"]
            except (json.JSONDecodeError, KeyError) as exc:
                on_failed(
                    f"terraform output: campo 'vm_ssh_endpoint' não encontrado. "
                    f"Erro: {exc}. Output: {r.stdout[:500]}"
                )
                return

            _log.info(
                "provision_ready",
                extra={"extras": {"vm_id": vm_id, "connection_hint": connection_hint}},
            )
            on_ready(connection_hint)

        except subprocess.TimeoutExpired:
            on_failed(
                f"Provisão de {vm_id!r} excedeu timeout de {timeout_sec}s. "
                "Aumente INFRA_PROVISION_TIMEOUT_SEC ou verifique o módulo terraform."
            )
        except Exception as exc:  # noqa: BLE001
            on_failed(f"Erro inesperado na provisão de {vm_id!r}: {exc}")
        finally:
            # Limpa plan file (gerado por terraform plan; arquivo binário temporário)
            plan_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # destroy                                                              #
    # ------------------------------------------------------------------ #
    def destroy(
        self,
        spec: str,
        vm_id: str,
        modules_root: Path | None,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        """Destrói a VM via terraform destroy em background thread.

        Backend local: verifica state file; se ausente → on_done() imediato (idempotente).
        Backend remoto: verifica workspace; se ausente → on_done() imediato.
        """
        if modules_root is None:
            on_done()
            return

        module_dir = modules_root / spec
        if not module_dir.is_dir():
            _log.warning(
                "destroy_skipped_no_module",
                extra={"extras": {"vm_id": vm_id, "spec": spec}},
            )
            on_done()
            return

        if self._backend_type == "local":
            state_file = module_dir / "states" / f"{vm_id}.tfstate"
            if not state_file.exists():
                _log.info(
                    "destroy_skipped_no_state",
                    extra={"extras": {"vm_id": vm_id, "spec": spec}},
                )
                on_done()
                return
        else:
            # Remote: apenas dispatch; workspace ausente é tratado no _run_destroy_remote
            state_file = None

        thread = threading.Thread(
            target=self._run_destroy,
            args=(spec, vm_id, module_dir, state_file, timeout_sec, on_done, on_failed),
            daemon=True,
            name=f"tf-destroy-{vm_id[:8]}",
        )
        thread.start()
        _log.info(
            "destroy_started",
            extra={"extras": {"vm_id": vm_id, "spec": spec, "thread": thread.name}},
        )

    def _run_destroy(
        self,
        spec: str,
        vm_id: str,
        module_dir: Path,
        state_file: Path | None,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        if self._backend_type == "local":
            self._run_destroy_local(spec, vm_id, module_dir, state_file, timeout_sec, on_done, on_failed)
        else:
            self._run_destroy_remote(spec, vm_id, module_dir, timeout_sec, on_done, on_failed)

    def _run_destroy_local(
        self,
        spec: str,
        vm_id: str,
        module_dir: Path,
        state_file: Path,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        tf = self._terraform_bin
        cwd = str(module_dir)
        state_str = str(state_file)

        try:
            _log.info(
                "terraform_destroy",
                extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": "local"}},
            )
            r = subprocess.run(
                [
                    tf, "destroy", "-auto-approve",
                    "-no-color", "-input=false",
                    f"-var=vm_id={vm_id}",
                    f"-var=spec={spec}",
                    f"-state={state_str}",
                    f"-state-out={state_str}",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if r.returncode != 0:
                on_failed(
                    f"terraform destroy falhou (vm_id={vm_id}):\n{r.stderr[:2000]}"
                )
                return

            state_file.unlink(missing_ok=True)
            _log.info(
                "destroy_complete",
                extra={"extras": {"vm_id": vm_id, "spec": spec}},
            )
            on_done()

        except subprocess.TimeoutExpired:
            on_failed(
                f"terraform destroy de {vm_id!r} excedeu timeout de {timeout_sec}s. "
                "Recurso pode ainda existir no cloud — verificar manualmente."
            )
        except Exception as exc:  # noqa: BLE001
            on_failed(f"Erro inesperado no destroy de {vm_id!r}: {exc}")

    def _run_destroy_remote(
        self,
        spec: str,
        vm_id: str,
        module_dir: Path,
        timeout_sec: int,
        on_done: OnDone,
        on_failed: OnFailed,
    ) -> None:
        tf = self._terraform_bin
        cwd = str(module_dir)

        try:
            # Verifica se workspace existe
            r_list = subprocess.run(
                [tf, "workspace", "list", "-no-color"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r_list.returncode != 0 or vm_id not in r_list.stdout:
                _log.info(
                    "destroy_skipped_no_workspace",
                    extra={"extras": {"vm_id": vm_id, "spec": spec}},
                )
                on_done()
                return

            # Seleciona workspace
            r_sel = subprocess.run(
                [tf, "workspace", "select", vm_id, "-no-color"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r_sel.returncode != 0:
                on_failed(
                    f"terraform workspace select {vm_id!r} falhou:\n{r_sel.stderr[:1000]}"
                )
                return

            _log.info(
                "terraform_destroy",
                extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": self._backend_type}},
            )
            r = subprocess.run(
                [
                    tf, "destroy", "-auto-approve",
                    "-no-color", "-input=false",
                    f"-var=vm_id={vm_id}",
                    f"-var=spec={spec}",
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if r.returncode != 0:
                on_failed(
                    f"terraform destroy falhou (vm_id={vm_id}):\n{r.stderr[:2000]}"
                )
                return

            # Volta para default e deleta workspace
            subprocess.run(
                [tf, "workspace", "select", "default", "-no-color"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            subprocess.run(
                [tf, "workspace", "delete", vm_id, "-no-color"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            _log.info(
                "destroy_complete",
                extra={"extras": {"vm_id": vm_id, "spec": spec, "backend": self._backend_type}},
            )
            on_done()

        except subprocess.TimeoutExpired:
            on_failed(
                f"terraform destroy de {vm_id!r} excedeu timeout de {timeout_sec}s. "
                "Recurso pode ainda existir no cloud — verificar manualmente."
            )
        except Exception as exc:  # noqa: BLE001
            on_failed(f"Erro inesperado no destroy remoto de {vm_id!r}: {exc}")
