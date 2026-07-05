# SPEC de Implementação — platform-dev-agent (DevTeam autônomo, Modo B)

> **Status:** Proposto — pronto para implementação do walking skeleton.
> **Data:** 2026-07-05
> **Escopo:** especificação única e consolidada da fundação (P0/P1) + motor de execução Modo B (P2) do novo repositório `platform-dev-agent`. Este documento já incorpora os fixes da revisão adversarial sênior — onde a especificação de design divergia da crítica, o fix da crítica prevaleceu e está embutido aqui **como o design**, não como TODO.

## Relação com documentos existentes

- **`MCP_PARITY_PLATFORM_MARKETING.md`**: este spec é a materialização do lado "devs" da paridade de arquitetura MCP. O `platform-dev-agent` copia a *forma* do `platform-marketing-agent` (padrão Plan-Approve-Execute, schemas Pydantic, loop ReAct por persona, fonte única perfil→tools) mas corrige os gotchas mapeados naquele documento e adota o padrão de governança como referência. As divergências são resolvidas aqui de forma travada (ver §0).
- **ADRs do repositório** (`ADR-001-PYTHON-POSTGRESQL-MIGRATION.md` e correlatos): herda-se o dialeto **Postgres/asyncpg** como runtime real desde o início (sem DDL MySQL divergente) e o padrão de repositórios `app/infrastructure/db/repositories`. O tom, a estrutura de decisão travada e o vocabulário de "copiar/adaptar/evitar" seguem os ADRs deste repo.

Todas as tools são invocadas **exclusivamente via gateway platform-mcp** (Streamable HTTP + OAuth 2.1). Nenhum caminho fala REST direto com backend nem importa tool in-process.

---

## §0. Decisões travadas

Estas decisões são pré-condição de todo o resto do documento e não são renegociadas nas seções seguintes.

| Decisão | Consequência de implementação |
|---|---|
| **MODO B** (Plan-Approve-Execute completo) | A fundação já expõe os hooks (`action_mode`, `RunbookSpec`) que a execução consome. **Nada de stubs "Fase C"**: tool ausente ⇒ item `ERROR`, nunca `DONE` falso. |
| **1 leader + N personas** (`security`, `qa_engineer`, `architecture`, `backend`, `frontend`, `devops`, `product_owner`, `product_manager`) | `PROFILES` é populado por **auto-discovery cruzado** (classe ↔ arquivo), nunca por dict hardcoded. |
| **Capability por verbo, ON por padrão, anexada à tool** | Uma **única autoridade de capability** (§2.4) deriva `read`/`write` do `operationId` com overrides; enforcement ativo em produção, sem flag opt-in. |
| **Tools SÓ via gateway platform-mcp** (Streamable HTTP + OAuth 2.1) | Não existe `MarketingApiClient` REST nem `bind_tools` sobre tools in-process arbitrárias. As tools vêm de um `GatewayToolProvider`/`GatewayToolClient`. |
| **Prompts de persona em ARQUIVO** | `ProfileBase.system_prompt()` lê `knowledge/profiles/<id>.md` com front-matter YAML; nunca string embutida no `.py`. |
| **Plano nasce de RUNBOOK declarativo (DAG versionado)** | `RUNBOOK_CATALOG` mora no repo, com `version` (SemVer). O plano é derivado por topo-sort do DAG — nunca improviso do LLM com fallback `"generic"`. |
| **Um único package root: `app/dev_agent/`** | Resolve a divergência P0 (`app.core.capability` / `app.modules.dev_agent`) vs P2 (`app.dev_agent.capability` / `app.dev_agent`). **Todo o código vive sob `app/dev_agent/`** — inclusive `capability.py`, que passa a ser `app/dev_agent/capability.py`. |
| **NÃO herdar gotchas** | Sem if/elif monolítico (dispatch table), sem LangGraph morto, sem `_CIRCUIT_BREAKER_THRESHOLD` inerte, sem bug de kwargs em `tasks_repo`, sem `agent_max_iterations` fantasma, sem UPDATE de status incondicional. |

---

## §1. Layout do repositório `platform-dev-agent`

Um único package root `app/dev_agent/` concentra o agente. `capability.py` fica **dentro** do package do agente (não em `app/core/`), consumido tanto pelo guard das personas quanto pelo enforcer do executor (§2.4).

```
platform-dev-agent/
├── app/
│   ├── core/
│   │   └── config.py                    # Settings (pydantic-settings), SEM nomes fantasma
│   ├── infrastructure/
│   │   └── db/
│   │       └── repositories/
│   │           └── tasks.py             # TasksRepository (assinaturas CORRIGIDAS)  [§2.3]
│   └── dev_agent/                        # ── PACKAGE ROOT ÚNICO ──
│       ├── capability.py                 # AUTORIDADE ÚNICA de capability (guard + enforcer) [§2.4]
│       ├── risk.py                       # RiskClassifier (high derivado, não allow-list nominal) [§3.2]
│       ├── orchestrator.py               # DevOrchestrator (leader/classifier) [§2.2]
│       ├── dispatch.py                   # dispatch table de action_mode (NÃO if/elif) [§2.2]
│       ├── runbook_selector.py           # RunbookSelector: (intent, entity) -> runbook_id [§3.3]
│       ├── handlers.py                   # handle_plan / handle_execute_plan / handle_analyze / ...
│       ├── profiles/
│       │   ├── base.py                   # ProfileBase (ReAct astream) [§2.1]
│       │   ├── loader.py                 # auto-discovery de personas [§2.1c]
│       │   ├── registry.py               # PROFILES populado por discovery [§2.1c]
│       │   └── backend.py                # subclasses mínimas (sem prompt embutido)
│       ├── registry/
│       │   ├── tool_registry.py          # TOOL_REGISTRY estendido (ToolContract) [§2.5]
│       │   └── profile_tools.py          # tools_for_profile / list_tool_contracts / assert_allowed [§2.5]
│       ├── runbook/
│       │   ├── catalog.py                # RUNBOOK_CATALOG + RunbookSpec (version) [§3.1]
│       │   └── dag.py                     # topological_order + detecção de ciclo [§3.1]
│       ├── plan/
│       │   ├── builder.py                # PlanBuilder (topo-sort + validação input_schema) [§3.4]
│       │   ├── approval.py               # ApprovalGate N1 + N2 [§3.5]
│       │   ├── executor.py               # PlanExecutor (guarded transitions, enforcement no try) [§3.6]
│       │   └── repository.py             # PlanRepository + reconciliação órfãos [§3.8/§4]
│       ├── gateway/
│       │   ├── mcp_client.py             # StreamableHTTP + OAuth 2.1 client p/ platform-mcp
│       │   ├── tool_provider.py          # GatewayToolProvider: tools/list -> LangChain tools
│       │   └── client.py                 # GatewayToolClient (tools/call do executor) [§3.7]
│       ├── security/
│       │   └── redaction.py              # redaction de segredos antes de persistir/reinjetar [§5.3]
│       └── models/
│           ├── chat.py                   # ChatRequest
│           └── plan.py                   # Plan / PlanItem / ItemResult (com required) [§3.1]
├── knowledge/
│   └── profiles/                         # PROMPTS EM ARQUIVO (fonte única de persona)
│       ├── security.md
│       ├── qa_engineer.md
│       ├── architecture.md
│       ├── backend.md
│       ├── frontend.md
│       ├── devops.md
│       ├── product_owner.md
│       └── product_manager.md
├── tests/
└── pyproject.toml
```

### COPIAR vs ADAPTAR vs EVITAR (estrutura)

- **COPIAR** (estrutura): o layout `app/modules/<agente>/{profiles,models}` + `app/infrastructure/db/repositories` do marketing-agent é sólido — mantém separação orquestrador/persona/repos. Aqui `modules/<agente>` vira o package único `app/dev_agent/`.
- **ADAPTAR**: substituir `app/infrastructure/http/marketing_client.py` (REST direto) por `app/dev_agent/gateway/` (Streamable HTTP + OAuth). Adicionar `app/dev_agent/capability.py` (autoridade única) e `knowledge/profiles/`.
- **EVITAR**:
  - Não criar `graph/` (LangGraph paralelo morto — `route_intent` chamando `_detect_profile(1 arg)` sobre `__new__` sem `__init__`).
  - Não colocar prompt de persona dentro de `.py`.
  - `SCHEMA_VERSION` etc. — usar nomes corretos desde o início (marketing tinha typo `"mka_schemka_version"`).

---

## §2. Fundação (P0/P1)

### §2.1. `ProfileBase` + personas lendo prompt de arquivo + auto-discovery

Copiado do loop ReAct de `profiles/base.py` do marketing, com 4 correções travadas: (1) `system_prompt()` **lê arquivo**; (2) tools já chegam **guardadas** por capability (não faz bind arbitrário); (3) `max_iterations` vem de atributo de classe real, não de setting fantasma; (4) chamadas ao `tasks_repo` com **kwargs corretos**.

```python
# app/dev_agent/profiles/base.py
from __future__ import annotations
import asyncio, time, logging
from abc import ABC
from pathlib import Path
from typing import Any, ClassVar
from langchain_core.messages import (
    BaseMessage, SystemMessage, HumanMessage, ToolMessage,
)
from app.core.config import settings
from app.dev_agent.security.redaction import redact_for_llm   # §5.3

logger = logging.getLogger(__name__)

# Raiz dos prompts em arquivo — fonte ÚNICA de persona.
PROFILES_DIR = Path(settings.knowledge_dir) / "profiles"


class ProfileParseError(RuntimeError):
    """Front-matter/markdown de persona inválido — falha explícita, sem fallback silencioso."""


class ProfileBase(ABC):
    # Identidade — pode ser sobrescrita OU derivada do front-matter (ver loader §2.1c).
    id: ClassVar[str] = ""              # ex. "backend" — casa com knowledge/profiles/backend.md
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    model: ClassVar[str] = "claude-sonnet-4-6"
    max_iterations: ClassVar[int] = 12  # real, por-perfil; NADA de agent_max_iterations fantasma
    front_matter: ClassVar[dict[str, Any]] = {}   # preenchido pelo loader

    def __init__(self, tools: list | None = None) -> None:
        # tools JÁ VÊM guardadas por CapabilityGuard (ver orchestrator §2.2).
        self._tools: list = list(tools or [])

    @property
    def tools(self) -> list:
        return self._tools

    # ---- PROMPT EM ARQUIVO (substitui o system_prompt() hardcoded do marketing) ----
    def system_prompt(self) -> str:
        return self._load_prompt_body()

    def _prompt_path(self) -> Path:
        return PROFILES_DIR / f"{self.id}.md"

    def _load_prompt_body(self) -> str:
        raw = self._prompt_path().read_text(encoding="utf-8")
        _, body = _split_front_matter(raw)   # ver loader §2.1c
        if not body.strip():
            raise ProfileParseError(f"Prompt vazio para persona '{self.id}'")
        return body

    def build_messages(self, user_message: str,
                       history: list[BaseMessage] | None = None) -> list[BaseMessage]:
        msgs: list[BaseMessage] = [SystemMessage(content=self.system_prompt())]
        if history:
            msgs.extend(history)
        msgs.append(HumanMessage(content=user_message))
        return msgs

    def _build_llm(self):
        from app.components.llm.factory import LLMFactory
        provider = LLMFactory.from_model(self.model)
        llm = provider.get_llm(model_code=self.model)
        if self._tools:
            llm = llm.bind_tools(self._tools)   # tools já guardadas por capability
        return llm

    def _apply_context(self, messages: list[BaseMessage],
                       context: dict[str, Any] | None) -> list[BaseMessage]:
        if context:
            ctx = "\n".join(f"{k}: {v}" for k, v in context.items())
            messages[0] = SystemMessage(content=f"{self.system_prompt()}\n\n## Contexto\n{ctx}")
        return messages

    async def astream(
        self, user_message: str, *,
        history: list[BaseMessage] | None = None,
        context: dict[str, Any] | None = None,
        callbacks: list | None = None,
        pool=None, run_id: str | None = None,
        session_id: str | None = None, message_id: str | None = None,
        budget=None,                     # RunBudget (§5.1) — tetos por-run
    ):
        from app.infrastructure.db.repositories.tasks import TasksRepository
        llm = self._build_llm()
        messages = self._apply_context(self.build_messages(user_message, history), context)
        tool_map = {t.name: t for t in self._tools}
        cfg = {"callbacks": callbacks} if callbacks else {}
        tasks_repo = TasksRepository(pool) if (pool and run_id and session_id) else None

        # CORREÇÃO do gotcha marketing: limite real por-perfil, não getattr fantasma.
        max_iter = self.max_iterations
        stream_timeout = settings.llm_stream_timeout_seconds  # 120

        for iteration in range(max_iter):
            if budget is not None:
                budget.check()   # levanta BudgetExceeded se estourar tokens/custo/wall-clock (§5.1)
            chunks: list = []
            try:
                it = llm.astream(messages, config=cfg).__aiter__()
                while True:
                    chunk = await asyncio.wait_for(it.__anext__(), timeout=stream_timeout)
                    text = _extract_text(chunk.content)
                    if text:
                        yield text
                    chunks.append(chunk)
            except StopAsyncIteration:
                pass
            except TimeoutError:
                yield f"\n\n_(Tempo limite de {stream_timeout:.0f}s atingido.)_"
                return
            if not chunks:
                break
            full = chunks[0]
            for c in chunks[1:]:
                try:
                    full = full + c
                except Exception:
                    pass
            if budget is not None:
                budget.add_usage(full)   # acumula tokens/custo do turn
            tool_calls = getattr(full, "tool_calls", None) or []
            if not tool_calls:
                break  # resposta final
            messages.append(full)

            for tc in tool_calls:
                if budget is not None:
                    budget.count_tool_call()   # teto de tool-calls por run (§5.1)
                name, args, tid = tc["name"], tc.get("args", {}), tc["id"]
                task_id = None
                if tasks_repo:
                    try:
                        # kwargs CORRETOS (marketing usava input_data/output/error → falha silenciosa)
                        task_id = await tasks_repo.create(
                            run_id=run_id, session_id=session_id, message_id=message_id,
                            profile=self.id, tool_name=name, input_json=args, iteration=iteration,
                        )
                        await tasks_repo.start(task_id)
                    except Exception:
                        task_id = None
                t0 = time.perf_counter()
                try:
                    tool = tool_map.get(name)
                    if tool is None:
                        raise ValueError(f"Tool '{name}' indisponível neste perfil")
                    result = await _invoke_with_retry(tool, args)
                    safe = redact_for_llm(name, result)   # §5.3 — segredos NÃO reinjetados no LLM
                    out = str(safe)
                    messages.append(ToolMessage(content=out, tool_call_id=tid))
                    if task_id:
                        try:
                            await tasks_repo.complete(
                                task_id, output_text=out,
                                duration_ms=int((time.perf_counter() - t0) * 1000))
                        except Exception:
                            pass
                    if callbacks:
                        await _fire(callbacks, "on_tool_end", name, out)
                except Exception as exc:
                    err = str(exc)
                    messages.append(ToolMessage(content=f"Erro ao executar tool: {err}",
                                                tool_call_id=tid))
                    if task_id:
                        try:
                            await tasks_repo.fail(
                                task_id, error_text=err,
                                duration_ms=int((time.perf_counter() - t0) * 1000))
                        except Exception:
                            pass
                    if callbacks:
                        await _fire(callbacks, "on_tool_error", name, err)


async def _invoke_with_retry(tool, args) -> Any:
    last: Exception | None = None
    for attempt in range(settings.tool_max_retries + 1):
        try:
            return await asyncio.wait_for(tool.ainvoke(args),
                                          timeout=settings.tool_timeout_seconds)
        except Exception as exc:
            last = exc
            if attempt < settings.tool_max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))
    assert last is not None
    raise last
```

Personas viram subclasses mínimas — **sem prompt embutido**:

```python
# app/dev_agent/profiles/backend.py
from app.dev_agent.profiles.base import ProfileBase

class BackendProfile(ProfileBase):
    id = "backend"          # casa com knowledge/profiles/backend.md
    max_iterations = 15
    # display_name/description/model podem vir 100% do front-matter (loader preenche).
```

#### (b) Formato do arquivo de persona — `knowledge/profiles/backend.md`

```markdown
---
id: backend
display_name: Backend Engineer
description: Implementa serviços, APIs e migrations.
model: claude-sonnet-4-6
max_iterations: 15
capabilities: [read, write]        # alimenta a autoridade de capability (§2.4)
capability_overrides:              # override por tool (precedência máxima)
  qa-mcp.run_tests: read
---
Você é o engenheiro de backend do time...
(corpo do system prompt em markdown livre)
```

#### (c) Auto-discovery — `loader.py` + `registry.py`

```python
# app/dev_agent/profiles/loader.py
from __future__ import annotations
import importlib, inspect, pkgutil, re
from pathlib import Path
from typing import Any
import yaml
from app.dev_agent.profiles.base import ProfileBase, PROFILES_DIR, ProfileParseError

_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

def _split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    m = _FM_RE.match(raw)
    if not m:
        raise ProfileParseError("Arquivo de persona sem front-matter YAML (--- ... ---)")
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2)

def discover_profiles() -> dict[str, type[ProfileBase]]:
    """
    Auto-discovery em DUAS fontes cruzadas (falha se divergirem):
      1. Subclasses de ProfileBase em app.dev_agent.profiles.*
      2. Arquivos knowledge/profiles/<id>.md
    Todo id de classe DEVE ter arquivo; todo arquivo DEVE ter classe.
    """
    import app.dev_agent.profiles as pkg
    classes: dict[str, type[ProfileBase]] = {}
    for _, modname, _ in pkgutil.iter_modules(pkg.__path__):
        if modname in ("base", "loader", "registry"):
            continue
        mod = importlib.import_module(f"{pkg.__name__}.{modname}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, ProfileBase) and obj is not ProfileBase and obj.id:
                classes[obj.id] = obj

    files = {p.stem for p in PROFILES_DIR.glob("*.md")}
    missing_file = set(classes) - files
    missing_class = files - set(classes)
    if missing_file or missing_class:
        raise ProfileParseError(
            f"Divergência persona↔arquivo: sem arquivo={missing_file}, sem classe={missing_class}")

    # injeta metadados do front-matter na classe (display_name, model, overrides…)
    for pid, cls in classes.items():
        meta, _ = _split_front_matter((PROFILES_DIR / f"{pid}.md").read_text(encoding="utf-8"))
        cls.front_matter = meta
        cls.display_name = meta.get("display_name", cls.display_name or pid)
        cls.description = meta.get("description", cls.description)
        cls.model = meta.get("model", cls.model)
        if "max_iterations" in meta:
            cls.max_iterations = int(meta["max_iterations"])
    return classes
```

```python
# app/dev_agent/profiles/registry.py
from app.dev_agent.profiles.loader import discover_profiles
PROFILES: dict[str, type] = discover_profiles()   # substitui o dict hardcoded do marketing
```

#### (d) COPIAR vs ADAPTAR vs EVITAR

- **COPIAR** verbatim (com correções): o núcleo do loop `astream` (streaming por-chunk com `asyncio.wait_for`, reconstrução `full`, `ToolMessage` no `messages`, retry+timeout por-tool).
- **ADAPTAR**: `system_prompt()` → leitura de arquivo com front-matter; `PROFILES` → auto-discovery; tools já guardadas por capability; redaction do output de tool antes de reinjetar no LLM (§5.3); teto por-run via `budget` (§5.1).
- **EVITAR (gotchas do marketing)**:
  - **Bug de kwargs** (`input_data`/`output`/`error` vs `input_json`/`output_text`/`error_text`) que fazia `mka_tasks` **nunca gravar** — corrigido acima.
  - **`agent_max_iterations` fantasma** (efetivo sempre 10) — aqui `max_iterations` é atributo de classe/front-matter real.
  - **`_CIRCUIT_BREAKER_THRESHOLD` inerte** — não portar; se quiser circuit-breaker, implementá-lo de fato (fora da fundação).

### §2.2. Leader/classifier (`DevOrchestrator`) + dispatch table

```python
# app/dev_agent/orchestrator.py
from __future__ import annotations
import asyncio, hashlib, json, time, logging
from collections import OrderedDict
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings
from app.dev_agent.profiles.registry import PROFILES
from app.dev_agent.registry.profile_tools import tools_for_profile
from app.dev_agent.dispatch import ACTION_HANDLERS   # dispatch table

logger = logging.getLogger(__name__)

_INTENT_SYSTEM = """Você é um classificador de intenção preciso para um agente de engenharia.
Retorne APENAS JSON:
{"profile":"<um de: security|qa_engineer|architecture|backend|frontend|devops|product_owner|product_manager>",
 "sub_intent":"<sub-intenção>","intent":"<1 frase>","confidence":0.0-1.0,
 "action_mode":"plan"|"analyze"|"guided_creation","entity_type":"<tipo ou null>"}
Se confidence < 0.6, use architecture como fallback."""


class _LRUCache:
    """Cache com maxsize + TTL — corrige o dict de classe sem bound do marketing (§1.5 crítica)."""
    def __init__(self, maxsize: int = 512):
        self._d: OrderedDict[str, tuple] = OrderedDict()
        self._max = maxsize

    def get(self, key):
        v = self._d.get(key)
        if v is None:
            return None
        if v[-1] <= time.monotonic():          # expirado
            self._d.pop(key, None)
            return None
        self._d.move_to_end(key)
        return v

    def set(self, key, value):
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self._max:
            self._d.popitem(last=False)         # descarta o mais antigo (bound real)


class DevOrchestrator:
    _INTENT_CACHE_TTL = 300

    def __init__(self, tenant_id: str, leader_llm, tool_provider):
        self._tenant_id = tenant_id
        self._leader_llm = leader_llm            # temperature=0.0
        self._tool_provider = tool_provider      # GatewayToolProvider
        self._intent_cache = _LRUCache(maxsize=512)   # instância, não atributo de classe

    async def _detect_profile(self, message, explicit_profile, cb):
        if explicit_profile and explicit_profile in PROFILES:
            return explicit_profile, message, "", "analyze", None
        key = hashlib.sha256(
            f"{self._tenant_id}:{message.strip().lower()}".encode()).hexdigest()[:16]
        c = self._intent_cache.get(key)
        if c:
            return c[:5]
        try:
            msgs = [SystemMessage(content=_INTENT_SYSTEM),
                    HumanMessage(content=f"<user_message>\n{message}\n</user_message>")]
            resp = await asyncio.wait_for(
                self._leader_llm.ainvoke(msgs, config={"callbacks": [cb]}),
                timeout=settings.llm_invoke_timeout_seconds)
            data = json.loads((getattr(resp, "content", "{}") or "{}").strip())
            profile = data.get("profile", "architecture")
            action_mode = data.get("action_mode", "analyze")
            confidence = float(data.get("confidence", 1.0))    # ENFORCED em Python, não só no prompt
            if profile not in PROFILES or confidence < 0.6:
                profile = "architecture"
            if action_mode not in ("plan", "analyze", "guided_creation"):
                action_mode = "analyze"
            result = (profile, data.get("intent", message[:100]),
                      data.get("sub_intent", ""), action_mode, data.get("entity_type") or None)
            self._intent_cache.set(key, (*result, time.monotonic() + self._INTENT_CACHE_TTL))
            return result
        except Exception:
            return "architecture", message[:100], "", "analyze", None

    async def stream(self, message, *, pool, session_id, user_id,
                     explicit_profile=None, context=None,
                     response_to_question_id=None, response_value=None):
        cb = ...  # tracking callback
        run_id = _new_run_id()
        message_id = _new_message_id()
        # sobreposições determinísticas (flow gathering > pending plan > LLM) — via repos
        active_flow = await self._get_active_flow(pool, session_id)
        pending_plan = await self._get_pending_plan(pool, response_to_question_id)
        profile, intent, sub, action_mode, entity = await self._detect_profile(
            message, explicit_profile, cb)
        action_mode = self._resolve_action_mode(action_mode, active_flow, pending_plan)

        handler = ACTION_HANDLERS[action_mode]   # DISPATCH TABLE — sem if/elif monolítico
        ctx = _StepContext(
            orchestrator=self, pool=pool, session_id=session_id, user_id=user_id,
            run_id=run_id, message_id=message_id,          # §1.6 crítica: SEMPRE presentes
            profile=profile, intent=intent, sub=sub, entity=entity,
            active_flow=active_flow, pending_plan=pending_plan,
            message=message, context=context, cb=cb,
            response_to_question_id=response_to_question_id, response_value=response_value,
        )
        async for ev in handler(ctx):
            yield ev
        # FLUSH final SEMPRE (mesmo em early-return de aprovação): run nunca fica sem status terminal
        await self._flush(ctx)
```

`_StepContext` é um dataclass com contrato **completo** (corrige §1.6 da crítica: `run_id`/`message_id`/`text_chunk` sempre definidos, senão nenhuma task é gravada — regressão silenciosa do próprio gotcha que dizemos corrigir):

```python
# app/dev_agent/handlers.py (trecho — contrato do contexto)
from dataclasses import dataclass, field
from typing import Any

@dataclass
class _StepContext:
    orchestrator: Any
    pool: Any
    session_id: str
    user_id: str
    run_id: str                     # obrigatório — sem ele TasksRepository não grava
    message_id: str
    profile: str
    intent: str
    sub: str
    entity: str | None
    active_flow: Any
    pending_plan: Any
    message: str
    context: dict | None
    cb: Any
    response_to_question_id: str | None = None
    response_value: Any = None

    def text_chunk(self, text: str) -> dict:
        return {"type": "text", "text": text}
```

```python
# app/dev_agent/dispatch.py — substitui o if/elif de 5 ramos do marketing
from typing import Callable, AsyncIterator
from app.dev_agent.handlers import (
    handle_plan, handle_execute_plan, handle_guided_creation,
    handle_advance_flow, handle_analyze,
)
ActionHandler = Callable[[object], AsyncIterator]
ACTION_HANDLERS: dict[str, ActionHandler] = {
    "plan": handle_plan,
    "execute_plan": handle_execute_plan,
    "guided_creation": handle_guided_creation,
    "advance_flow": handle_advance_flow,
    "analyze": handle_analyze,
}
```

`handle_analyze` monta as tools guardadas e roda a persona:

```python
async def handle_analyze(ctx):
    profile_cls = PROFILES[ctx.profile]
    tools = ctx.orchestrator._tool_provider.build_guarded_tools(
        contracts=tools_for_profile(ctx.profile),   # fonte única §2.5
        profile_id=ctx.profile,
    )
    inst = profile_cls(tools=tools)
    budget = RunBudget.for_run(ctx.run_id)           # §5.1
    async for tok in inst.astream(ctx.message, context=ctx.context, callbacks=[ctx.cb],
                                  pool=ctx.pool, run_id=ctx.run_id,
                                  session_id=ctx.session_id, message_id=ctx.message_id,
                                  budget=budget):
        yield ctx.text_chunk(tok)
```

`handle_plan` (esqueleto — depende do `RunbookSelector` §3.3 e do `PlanBuilder` §3.4):

```python
async def handle_plan(ctx):
    runbook_id = ctx.orchestrator._runbook_selector.select(
        intent=ctx.intent, entity_type=ctx.entity, sub_intent=ctx.sub, message=ctx.message)
    if runbook_id is None:
        # sem runbook aplicável → cai em análise, nunca improvisa plano
        async for ev in handle_analyze(ctx):
            yield ev
        return
    plan = ctx.orchestrator._plan_builder.build_from_runbook(
        runbook_id=runbook_id, session_id=ctx.session_id, inputs_by_task=_gather_inputs(ctx))
    await ctx.orchestrator._plan_repo.create(plan)
    yield ctx.text_chunk(plan.explanation)
    yield _approval_poll(plan)          # N1 (+ N2 se houver risk=high, ver §3.5)
```

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR**: `_detect_profile` (bypass explícito + cache TTL + fallback estrutural); o padrão de fonte única `list_tool_contracts(caller=)`.
- **ADAPTAR**: (1) `if/elif` de 5 ramos → **dispatch table** `ACTION_HANDLERS`; (2) `MarketingApiClient` REST → `GatewayToolProvider`; (3) `_PROFILE_TOOLS` dict → `tools_for_profile()` derivado do `TOOL_REGISTRY`; (4) `confidence` **enforced em Python**; (5) cache de intenção com `maxsize`/LRU (não dict de classe sem bound — §1.5 crítica).
- **EVITAR (gotchas)**:
  - **confidence não lido** — aqui o Python aplica o threshold.
  - **TOCTOU flow×plano** silencioso — `_resolve_action_mode` deve **resolver** (não só logar) o conflito; precedência **flow > plan > LLM**, serializado por lock.
  - **early-return sem flush** — `stream()` garante `_flush(ctx)` sempre.
  - **cache não-normalizado / sem bound** — chave inclui `.strip().lower()`; `_LRUCache` purga expirados e limita tamanho.
  - **`_StepContext` incompleto** — `run_id`/`message_id`/`text_chunk` sempre presentes.

### §2.3. `TasksRepository` — assinaturas corrigidas

```python
# app/infrastructure/db/repositories/tasks.py (assinaturas — corpo asyncpg/Postgres)
class TasksRepository:
    async def create(self, *, run_id: str, session_id: str, message_id: str | None,
                     profile: str, tool_name: str, input_json: dict,
                     iteration: int = 0) -> str: ...
    async def start(self, task_id: str) -> None: ...
    async def complete(self, task_id: str, *, output_text: str, duration_ms: int = 0) -> None: ...
    async def fail(self, task_id: str, *, error_text: str, duration_ms: int = 0) -> None: ...
```

- **EVITAR**: os nomes que o marketing usava no call-site (`input_data`, `output=`, `error=`) divergiam da repo (`input_json`, `output_text`, `error_text`) e eram engolidos por `try/except`. Aqui o call-site (§2.1) e a assinatura estão alinhados.

### §2.4. Autoridade ÚNICA de capability (guard + enforcer no mesmo módulo)

**Fix da revisão §1.1 embutido:** existe **uma única autoridade de capability**, num único módulo `app/dev_agent/capability.py`, consumida pelos **dois** caminhos de execução: (a) o `CapabilityGuard` que embrulha a tool antes de entregá-la à persona no `astream`; (b) o `CapabilityEnforcer` que valida cada item no `PlanExecutor` antes de chamar o gateway. Ambos derivam a mesma decisão da **mesma função `resolve_capability`** e do **mesmo modelo de permissão por perfil** (`capabilities` do front-matter → `allowed[profile]`). Não há dois formatos de allow-list divergentes: a autorização é sempre "o perfil `X` tem a capability `Y`?".

```python
# app/dev_agent/capability.py — AUTORIDADE ÚNICA
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Capability(StrEnum):
    READ = "read"
    WRITE = "write"


# Verbos → WRITE (decisão travada); qualquer outro → READ.
WRITE_PREFIXES = ("create_", "update_", "delete_", "generate_", "deploy_",
                  "push_", "merge_", "destroy_", "promote_", "rollback",
                  "trigger_", "tag_", "apply_", "revoke_", "rotate_")


def derive_capability(tool: str) -> Capability:
    """Capability por VERBO a partir do operationId (parte após 'namespace.')."""
    op = tool.split(".", 1)[1] if "." in tool else tool
    return Capability.WRITE if op.startswith(WRITE_PREFIXES) else Capability.READ


def resolve_capability(tool: str, *, contract_override: str | None = None,
                       profile_overrides: dict[str, str] | None = None) -> Capability:
    """Precedência ÚNICA (mesma para os dois caminhos):
       override do perfil (front-matter) > override do contrato/runbook > verbo."""
    if profile_overrides and tool in profile_overrides:
        return Capability(profile_overrides[tool])
    if contract_override:
        return Capability(contract_override)
    return derive_capability(tool)


class CapabilityViolation(PermissionError):
    """Perfil sem permissão para a capability requerida pela tool."""


@dataclass
class CapabilityAuthority:
    """Autoridade única. `allowed` vem do front-matter (§2.1b): profile -> {READ, WRITE}.
    Enforcement ON por padrão — não há flag para desligar em produção."""
    allowed: dict[str, set[Capability]]

    @classmethod
    def from_profiles(cls, profiles: dict[str, type]) -> "CapabilityAuthority":
        allowed: dict[str, set[Capability]] = {}
        for pid, pcls in profiles.items():
            caps = (pcls.front_matter or {}).get("capabilities", ["read"])
            allowed[pid] = {Capability(c) for c in caps}
        return cls(allowed=allowed)

    def assert_allowed(self, *, profile: str, capability: Capability, tool: str) -> None:
        """CAMINHO EXECUTOR (PlanExecutor). Levanta CapabilityViolation."""
        granted = self.allowed.get(profile, {Capability.READ})
        if capability not in granted:
            raise CapabilityViolation(
                f"perfil={profile!r} não tem capability={capability} para tool={tool!r}")

    # ---- CAMINHO PERSONA (guard-na-tool no astream) ----
    def wrap(self, raw_tool, *, contract, profile_id: str):
        """Embrulha a tool para a persona. Usa a MESMA resolução/permissão do executor."""
        overrides = (self._profiles[profile_id].front_matter or {}).get("capability_overrides")
        cap = resolve_capability(contract.tool,
                                 contract_override=getattr(contract, "capability", None),
                                 profile_overrides=overrides)
        setattr(raw_tool, "capability", cap.value)         # metadado anexado (auditável)
        setattr(raw_tool, "tool_contract", contract.tool)
        try:
            self.assert_allowed(profile=profile_id, capability=cap, tool=contract.tool)
        except CapabilityViolation as exc:
            return self._deny_tool(raw_tool, str(exc))     # nega, mas schema fica visível ao LLM
        return raw_tool

    def _deny_tool(self, raw_tool, reason: str):
        async def _blocked(**kwargs):
            raise CapabilityViolation(reason)              # vira item ERROR no astream, nunca done falso
        raw_tool.coroutine = _blocked
        return raw_tool
```

> **Nota:** `CapabilityGuard.wrap` (persona) e `CapabilityAuthority.assert_allowed` (executor) são o **mesmo objeto** (`CapabilityAuthority`), consumindo `resolve_capability` e `allowed[profile]`. Uma ação write não pode passar por um caminho e escapar do outro — ambos consultam a mesma autoridade.

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR**: a ideia de `assert_allowed`/`PermissionError` de `tool_matrix.py` (autorização por caller).
- **ADAPTAR**: elevar de "quem pode chamar" (caller) para "**o que pode fazer**" (read/write por verbo); **anexar** a capability ao objeto tool (`setattr`) para o caminho persona e enforçar no dispatch para o caminho executor — ambos na mesma autoridade.
- **EVITAR**:
  - **enforcement opt-in** — ON por padrão; sem flag para desligar em produção.
  - **capability só no prompt** — aqui é enforced em código.
  - **tool que "parece done" sem executar** — a tool negada **levanta** `CapabilityViolation`, nunca retorna sucesso falso.
  - **duas fontes de verdade divergentes** (§1.1 crítica) — uma única `CapabilityAuthority`.

### §2.5. `TOOL_REGISTRY` estendido + fonte única perfil→tools

```python
# app/dev_agent/registry/tool_registry.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum

class OperationKind(StrEnum):
    READ = "read"; MUTATION = "mutation"; PROJECTION = "projection"
    KNOWLEDGE = "knowledge"; CONTRACT = "contract"

@dataclass(frozen=True)
class ToolContract:
    tool: str                         # "qa-mcp.run_tests" (namespace.operationId do gateway)
    owner: str
    operation: OperationKind
    allowed_callers: list[str]        # ids de perfil (backend, devops, ...)
    entities: list[str] = field(default_factory=list)
    emits: list[str] = field(default_factory=list)
    capability: str | None = None     # override explícito (senão derivar de operationId — §2.4)
    notes: str = ""

    def to_dict(self) -> dict: ...

# grupos reutilizáveis de callers
ALL_PROFILES = ["security","qa_engineer","architecture","backend",
                "frontend","devops","product_owner","product_manager"]
BUILD_CALLERS = ["backend","frontend","devops"]

TOOL_REGISTRY: list[ToolContract] = [
    ToolContract("qa-mcp.run_tests", owner="qa-mcp", operation=OperationKind.READ,
                 allowed_callers=BUILD_CALLERS + ["qa_engineer"]),
    ToolContract("deploy-mcp.create_deployment", owner="deploy-mcp",
                 operation=OperationKind.MUTATION, allowed_callers=["devops"]),
    ToolContract("infra-mcp.destroy_infrastructure", owner="infra-mcp",
                 operation=OperationKind.MUTATION, allowed_callers=["devops"]),
    # ...
]
```

```python
# app/dev_agent/registry/profile_tools.py — FONTE ÚNICA (derivado, não duplicado)
from app.dev_agent.registry.tool_registry import TOOL_REGISTRY

def list_tool_contracts(owner=None, caller=None) -> list[dict]:
    cs = TOOL_REGISTRY
    if owner:  cs = [c for c in cs if c.owner == owner]
    if caller: cs = [c for c in cs if caller in c.allowed_callers]
    return [c.to_dict() for c in cs]

def tools_for_profile(profile_id: str) -> list:
    """allowed_tools DERIVADO da matriz — perfil não duplica lista."""
    return [c for c in TOOL_REGISTRY if profile_id in c.allowed_callers]

def assert_allowed(tool: str, caller: str) -> None:
    for c in TOOL_REGISTRY:
        if c.tool == tool:
            if caller not in c.allowed_callers:
                raise PermissionError(f"{caller} não pode chamar {tool}")
            return
    raise ValueError(f"Tool desconhecida: {tool}")
```

Transporte — só via gateway (Streamable HTTP + OAuth):

```python
# app/dev_agent/gateway/tool_provider.py
class GatewayToolProvider:
    """Descobre tools do platform-mcp via tools/list e as embrulha em LangChain tools
    guardadas pela CapabilityAuthority. NUNCA importa backend in-process nem chama REST direto."""
    def __init__(self, mcp_client, capability_authority):
        self._client = mcp_client                # StreamableHTTP + OAuth 2.1
        self._authority = capability_authority   # §2.4 (mesma autoridade do executor)

    async def refresh_catalog(self) -> None:
        self._catalog = await self._client.tools_list()

    def build_guarded_tools(self, *, contracts: list, profile_id: str) -> list:
        tools = []
        for c in contracts:
            raw = self._client.as_langchain_tool(c.tool)
            tools.append(self._authority.wrap(raw, contract=c, profile_id=profile_id))
        return tools
```

---

## §3. Motor Modo B (P2)

### §3.1. Schema `Plan` / `PlanItem` / `ItemResult` (com `required`)

**Fix da revisão §1.8 embutido:** `RunbookTaskSpec.required` é **propagado** ao `PlanItem` (`required: bool`), pois `_final_status` (§3.6) usa essa semântica: item `required` que falha → `FAILED`; opcional que falha → `PARTIAL`.

```python
# app/dev_agent/models/plan.py
from __future__ import annotations
import uuid
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, Field, field_validator
from app.dev_agent.capability import Capability


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ItemStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"              # dependências satisfeitas, aguardando execução
    APPROVED = "approved"        # gate de risk=high liberado individualmente
    EXECUTING = "executing"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"          # dep falhou / não selecionado / não confirmado
    NEEDS_RECONFIRM = "needs_reconfirm"   # §4 — write preso em EXECUTING no resume


class PlanStatus(StrEnum):
    PENDING = "pending"          # aguardando aprovação
    APPROVED = "approved"        # aprovado, ainda não iniciado
    EXECUTING = "executing"
    DONE = "done"
    PARTIAL = "partial"          # done_count < total, sem falha de item required
    FAILED = "failed"            # falha bloqueante (item required com ERROR)
    REJECTED = "rejected"
    EXPIRED = "expired"          # §5.2 — TTL de aprovação estourou


class PlanItem(BaseModel):
    """Uma ação atômica do plano, ligada a UMA tool do gateway."""
    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str
    sequence_num: int

    # Origem no runbook (rastreabilidade DAG)
    runbook_id: str
    task_id: str                       # chave da task no runbook
    depends_on: list[str] = Field(default_factory=list)  # task_ids do MESMO plano

    # Ação concreta — SEMPRE uma tool do gateway, nunca endpoint REST
    tool: str                          # "<namespace>.<operationId>", ex "qa-mcp.run_tests"
    capability: Capability             # anexada ao item — enforcement ON
    risk: RiskLevel = RiskLevel.LOW    # high => requer aprovação individual (N2)
    required: bool = True              # §1.8 crítica — propagado do RunbookTaskSpec

    label: str = Field(max_length=120)
    description: str | None = None
    responsible: str                   # persona/role dono do passo
    input_data: dict[str, Any] = Field(default_factory=dict)

    # Idempotência por item (correlação; NÃO depende de dedup do gateway — ver §4)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

    status: ItemStatus = ItemStatus.PENDING
    output_json: dict[str, Any] | None = None
    error_text: str | None = None

    @field_validator("tool")
    @classmethod
    def _tool_is_namespaced(cls, v: str) -> str:
        if "." not in v or v.startswith("http") or " " in v:
            raise ValueError(
                f"tool deve ser '<namespace>.<operationId>' (gateway MCP), recebido: {v!r}")
        return v


class Plan(BaseModel):
    """Plano estruturado derivado de um runbook DAG, antes de executar."""
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    run_id: str | None = None

    question_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:16]}")

    runbook_id: str
    runbook_version: str               # DAG versionado — trava a origem do plano
    title: str
    summary: str
    explanation: str                   # markdown exibido ao humano
    responsible_profile: str

    status: PlanStatus = PlanStatus.PENDING
    items: list[PlanItem]

    def requires_high_risk_approval(self) -> bool:
        return any(i.risk is RiskLevel.HIGH for i in self.items)

    def item_by_task(self, task_id: str) -> PlanItem | None:
        return next((i for i in self.items if i.task_id == task_id), None)


class ItemResult(BaseModel):
    """Resultado da execução de um item (retorno do executor)."""
    item_id: str
    task_id: str
    tool: str
    status: ItemStatus                 # done | error | skipped | needs_reconfirm
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    skip_reason: str | None = None     # §5.2 — distingue "por escolha" de "por falta de resposta"
```

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR** de `platform-marketing-agent/.../models/plan.py`: a tríade `PlanItem`/`Plan`/`ItemResult`; `item_id` gerado no servidor; `question_id` no formato `plan_<hex16>`; ciclos de status.
- **ADAPTAR**: (1) `action_type`+`endpoint` REST → **`tool` namespaced do gateway** (validador rejeita URLs/endpoints REST); (2) `capability`/`risk`/`required` **anexados ao item**; (3) `depends_on`/`task_id`/`runbook_id`/`runbook_version` amarram o item ao **DAG versionado**; (4) `idempotency_key` por item; (5) estados `NEEDS_RECONFIRM` (§4) e `EXPIRED` (§5.2); (6) `skip_reason` para distinguir motivos de skip.
- **EVITAR**: `action_type` livre + `endpoint` "MÉTODO /path"; item fallback `action_type="generic"`; acesso misto `dict.get()` × atributo.

### §3.2. `RiskClassifier` — high derivado, não allow-list nominal

**Fix da revisão §1.2 embutido:** `risk=high` é derivado de `operation == MUTATION AND owner in {deploy, infra, pipeline}` como **default**, com override explícito. **Não** se usa allow-list nominal frágil — tools como `push_acr`, `push_to_registry`, `merge_branch`, `destroy_infrastructure`, `trigger_workflow`, `tag_release` não podem escapar por não estarem num set literal.

```python
# app/dev_agent/risk.py
from __future__ import annotations
from app.dev_agent.capability import Capability
from app.dev_agent.models.plan import RiskLevel

# Owners cujas MUTATIONs são intrinsecamente destrutivas → high por default.
_HIGH_RISK_OWNERS = {"deploy-mcp", "infra-mcp", "pipeline-mcp"}


class RiskClassifier:
    def classify(self, *, tool: str, owner: str, operation: str,
                 cap: Capability, override: str | None = None) -> RiskLevel:
        if override:
            return RiskLevel(override)
        # DEFAULT robusto: qualquer MUTATION de owner sensível é high, independente do nome.
        if operation == "mutation" and owner in _HIGH_RISK_OWNERS:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM if cap is Capability.WRITE else RiskLevel.LOW
```

- **COPIAR** de `tool_matrix.py`: conceito de fonte única e `assert_allowed`.
- **ADAPTAR**: `risk` é conceito novo (não existe no marketing) e alimenta o gate N2. High **derivado de operation+owner**, não de nome de tool.
- **EVITAR**: allow-list nominal de tools high-risk (frágil — §1.2 crítica); enforcement opt-in.

### §3.3. `RunbookSelector` — (intent, entity) → runbook_id

**Fix da revisão §1.3 embutido:** `_detect_profile` devolve `action_mode="plan"` mas **não** um `runbook_id`. Sem o componente que mapeia (intent, entity_type) → `runbook_id`, `handle_plan` não constrói plano nenhum. O `RunbookSelector` é **determinístico com enum fechado** (a fonte de verdade), e o LLM só entra como **fallback** quando o mapa determinístico não casa — sempre restrito ao enum de `runbook_id`s existentes (nunca inventa id).

```python
# app/dev_agent/runbook_selector.py
from __future__ import annotations
import asyncio, json, logging
from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG

logger = logging.getLogger(__name__)

# Mapa DETERMINÍSTICO (fonte de verdade). Chave = (entity_type, sub_intent) normalizados.
# Enum FECHADO: só runbook_ids que existem no RUNBOOK_CATALOG.
_DETERMINISTIC_MAP: dict[tuple[str, str], str] = {
    ("service", "deploy"):     "deploy_service_pipeline",
    ("service", "healthcheck"): "healthcheck_readonly",
    ("infra",   "provision"):  "provision_infra",
    # ...
}


class RunbookSelector:
    def __init__(self, leader_llm=None):
        self._leader_llm = leader_llm
        self._valid = set(RUNBOOK_CATALOG.keys())   # enum fechado

    def select(self, *, intent: str, entity_type: str | None,
               sub_intent: str, message: str) -> str | None:
        # 1) determinístico
        key = ((entity_type or "").strip().lower(), (sub_intent or "").strip().lower())
        rb = _DETERMINISTIC_MAP.get(key)
        if rb and rb in self._valid:
            return rb
        # 2) fallback LLM — restrito ao enum fechado, NUNCA inventa id
        if self._leader_llm is not None:
            rb = self._select_via_llm(intent=intent, message=message)
            if rb in self._valid:
                return rb
        # 3) nenhum runbook aplicável → caller cai em análise (handle_plan §2.2)
        return None

    def _select_via_llm(self, *, intent: str, message: str) -> str | None:
        options = sorted(self._valid)
        prompt = (
            "Escolha UM runbook_id da lista fechada para a intenção. "
            f"Responda APENAS JSON {{\"runbook_id\": <um de {options} ou null>}}.\n"
            f"Intenção: {intent}\nMensagem: {message}"
        )
        try:
            resp = self._leader_llm.invoke(prompt)   # síncrono/curto; ou awaitable no caller
            data = json.loads(getattr(resp, "content", "{}") or "{}")
            rid = data.get("runbook_id")
            return rid if rid in self._valid else None
        except Exception:
            logger.warning("RunbookSelector: fallback LLM falhou; sem runbook")
            return None
```

- **EVITAR**: LLM escolhendo runbook livre (só enum fechado); `handle_plan` sem origem de plano.

### §3.4. Runbook DAG + `PlanBuilder` (topo-sort + validação de input)

**Fix da revisão §1.4 embutido:** `PlanBuilder` valida `input_data` contra `input_schema` do `RunbookTaskSpec` e **falha cedo** se um item `required` estiver sem inputs — numa execução autônoma, inputs vazios/errados não podem chegar ao gateway.

```python
# app/dev_agent/runbook/catalog.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunbookTaskSpec:
    title: str
    description: str
    required: bool
    responsible: str                    # security | qa_engineer | architecture | backend
                                        # | frontend | devops | product_owner | product_manager
    tool: str                           # "<namespace>.<operationId>" — fonte única aqui
    input_schema: dict                  # JSON-schema dos inputs esperados
    depends_on: list[str] = field(default_factory=list)   # task_ids do MESMO runbook (arestas DAG)
    capability_override: str | None = None   # força read/write; senão derivado do verbo
    risk_override: str | None = None         # força low/medium/high; senão heurística


@dataclass(frozen=True)
class RunbookSpec:
    id: str
    version: str                         # VERSIONADO (SemVer) — trava o plano gerado
    name: str
    description: str
    responsible_profile: str
    tasks: dict[str, RunbookTaskSpec]    # chave = task_id (alvo de depends_on)


RUNBOOK_CATALOG: dict[str, RunbookSpec] = { ... }   # constante import-time


def get_runbook(runbook_id: str) -> RunbookSpec:
    rb = RUNBOOK_CATALOG.get(runbook_id)
    if rb is None:
        raise ValueError(f"Runbook '{runbook_id}' inexistente. Disponíveis: {list(RUNBOOK_CATALOG)}")
    return rb
```

```python
# app/dev_agent/runbook/dag.py
from __future__ import annotations
from app.dev_agent.runbook.catalog import RunbookSpec


class RunbookDAGError(ValueError):
    """Ciclo ou aresta inválida no DAG do runbook."""


def topological_order(rb: RunbookSpec) -> list[str]:
    """Kahn topo-sort. Levanta RunbookDAGError em ciclo ou depends_on órfão."""
    tasks = rb.tasks
    indeg: dict[str, int] = {tid: 0 for tid in tasks}
    adj: dict[str, list[str]] = {tid: [] for tid in tasks}
    for tid, spec in tasks.items():
        for dep in spec.depends_on:
            if dep not in tasks:
                raise RunbookDAGError(f"[{rb.id}] task {tid!r} depende de {dep!r} inexistente")
            adj[dep].append(tid)
            indeg[tid] += 1
    queue = sorted(t for t, d in indeg.items() if d == 0)
    order: list[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
        queue.sort()
    if len(order) != len(tasks):
        raise RunbookDAGError(f"[{rb.id}] ciclo detectado no DAG (ordenadas {len(order)}/{len(tasks)})")
    return order
```

```python
# app/dev_agent/plan/builder.py
from __future__ import annotations
from jsonschema import validate as jsonschema_validate, ValidationError
from app.dev_agent.models.plan import Plan, PlanItem, RiskLevel
from app.dev_agent.runbook.catalog import RunbookSpec, get_runbook
from app.dev_agent.runbook.dag import topological_order
from app.dev_agent.capability import resolve_capability, Capability
from app.dev_agent.risk import RiskClassifier
from app.dev_agent.registry.tool_registry import TOOL_REGISTRY

_CONTRACT_BY_TOOL = {c.tool: c for c in TOOL_REGISTRY}

# Cap de itens por plano (§5.1 — fan-out) — rejeita plano gigante.
MAX_ITEMS_PER_PLAN = 50


class PlanBuildError(ValueError):
    """Runbook não gera plano válido (input required faltando, tool desconhecida, DAG inválido)."""


class PlanBuilder:
    def __init__(self, risk: RiskClassifier) -> None:
        self._risk = risk

    def build_from_runbook(
        self, *, runbook_id: str, session_id: str,
        inputs_by_task: dict[str, dict] | None = None,
        selected_tasks: set[str] | None = None,
    ) -> Plan:
        rb: RunbookSpec = get_runbook(runbook_id)
        order = topological_order(rb)               # falha cedo em ciclo/órfão
        inputs_by_task = inputs_by_task or {}

        draft = Plan(
            session_id=session_id, runbook_id=rb.id, runbook_version=rb.version,
            title=rb.name, summary=rb.description,
            explanation=self._render_explanation(rb, order),
            responsible_profile=rb.responsible_profile, items=[],
        )

        items: list[PlanItem] = []
        seq = 0
        for task_id in order:
            if selected_tasks is not None and task_id not in selected_tasks:
                continue
            spec = rb.tasks[task_id]
            inputs = inputs_by_task.get(task_id, {})

            # §1.4 crítica — VALIDA input_data contra input_schema; falha cedo se required sem inputs
            self._validate_inputs(rb.id, task_id, spec, inputs)

            contract = _CONTRACT_BY_TOOL.get(spec.tool)
            if contract is None:
                raise PlanBuildError(f"[{rb.id}] task {task_id}: tool {spec.tool!r} fora do TOOL_REGISTRY")

            cap = resolve_capability(spec.tool, contract_override=spec.capability_override)
            risk = self._risk.classify(tool=spec.tool, owner=contract.owner,
                                       operation=contract.operation.value, cap=cap,
                                       override=spec.risk_override)
            seq += 1
            items.append(PlanItem(
                plan_id=draft.plan_id, sequence_num=seq, runbook_id=rb.id, task_id=task_id,
                depends_on=list(spec.depends_on), tool=spec.tool, capability=cap, risk=risk,
                required=spec.required,                      # §1.8 — propaga required
                label=spec.title[:120], description=spec.description,
                responsible=spec.responsible, input_data=inputs,
            ))

        if len(items) > MAX_ITEMS_PER_PLAN:
            raise PlanBuildError(f"[{rb.id}] plano com {len(items)} itens excede o teto {MAX_ITEMS_PER_PLAN}")

        draft.items = items
        return draft

    @staticmethod
    def _validate_inputs(rb_id, task_id, spec, inputs) -> None:
        try:
            jsonschema_validate(instance=inputs, schema=spec.input_schema)
        except ValidationError as exc:
            if spec.required:
                raise PlanBuildError(
                    f"[{rb_id}] task {task_id} (required) com input inválido: {exc.message}") from exc
            # opcional com input inválido → item não é adicionado ao plano (não bloqueia)

    @staticmethod
    def _render_explanation(rb: RunbookSpec, order: list[str]) -> str:
        lines = [f"## {rb.name}\n", rb.description, "\n### Passos (ordem de execução)\n"]
        for i, tid in enumerate(order, 1):
            t = rb.tasks[tid]
            dep = f" (após: {', '.join(t.depends_on)})" if t.depends_on else ""
            flag = "" if t.required else " _(opcional)_"
            lines.append(f"{i}. **{t.title}** — {t.responsible}{dep}{flag}")
        return "\n".join(lines)
```

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR** de `runbook_catalog.py`: dataclasses frozen `RunbookTaskSpec`/`RunbookSpec`; `depends_on` como arestas intra-runbook; catálogo import-time; `get_runbook()`.
- **ADAPTAR**: (1) task carrega **a `tool` diretamente** (fonte única no próprio spec, sem mapa paralelo); (2) `version` no `RunbookSpec` → grava `runbook_version` no `Plan`; (3) `capability_override`/`risk_override`; (4) **`topological_order()` real**; (5) **validação `input_data`×`input_schema`** e propagação de `required` (§1.4/§1.8 crítica); (6) cap de itens por plano (§5.1).
- **EVITAR**: plano via LLM livre com fallback `"generic"`; DAG só declarativo sem topo-sort; omitir campos do serializer.

### §3.5. `ApprovalGate` — N1 (plano) + N2 (risk=high)

Dois níveis: **(N1)** aprovação do plano via `poll_multi`; **(N2)** gate adicional **por item `risk=high`**, com confirmação explícita e granular. "Aprovar todos" **nunca** cobre high-risk.

**Fix da revisão §2.3/§1.11 embutido:** distingue-se "pulado por escolha" de "pulado por falta de resposta". Um high-risk que era o objetivo do usuário mas não recebeu confirmação **não** é silenciosamente `SKIPPED` como se rejeitado — ele sinaliza `skip_reason="high_risk_unanswered"` e o plano fica visível como pendente de reconfirmação (não some).

```python
# app/dev_agent/plan/approval.py
from __future__ import annotations
from dataclasses import dataclass, field
from app.dev_agent.models.plan import Plan, RiskLevel


@dataclass
class ApprovalDecision:
    approved_item_ids: set[str]
    high_risk_confirmed_ids: set[str]           # subset explícito dos risk=high liberados
    high_risk_unanswered_ids: set[str] = field(default_factory=set)  # §1.11 — nem confirmado nem rejeitado
    rejected: bool = False


class ApprovalGate:
    """
    Regras:
      - N1: item só executa se estiver em approved_item_ids.
      - N2: item risk=high só executa se ALSO estiver em high_risk_confirmed_ids
            (confirmação individual, nunca coberta por "aprovar todos").
      - high-risk aprovado em N1 mas não confirmado em N2 => high_risk_unanswered (NÃO é rejeição).
      - Sem seleção e sem confirmação => NÃO executa (re-emite poll).
    """
    _VERBAL_APPROVE_ALL = frozenset({
        "sim", "ok", "pode", "aprovar", "executar", "pode executar",
        "aprovar todos", "executar tudo", "confirmar",
    })

    def resolve(self, plan: Plan, *, response_value, high_risk_response=None) -> ApprovalDecision:
        approved_labels: set[str] = set()
        explicit_all = response_value == "__approve_all__"
        if isinstance(response_value, list):
            approved_labels = set(response_value)
        elif isinstance(response_value, str) and not explicit_all:
            if response_value.lower().strip() in self._VERBAL_APPROVE_ALL:
                explicit_all = True

        if not approved_labels and not explicit_all:
            return ApprovalDecision(set(), set(), rejected=False)   # caller re-emite poll N1

        selected = (list(plan.items) if explicit_all
                    else [i for i in plan.items if i.label in approved_labels])
        approved_ids = {i.item_id for i in selected}

        # N2: high-risk exige confirmação individual por item_id (segundo poll dedicado).
        high_ids = {i.item_id for i in selected if i.risk is RiskLevel.HIGH}
        confirmed = self._confirmed_high(high_risk_response, high_ids)
        unanswered = high_ids - confirmed        # §1.11 — nem confirmado nem explicitamente rejeitado

        return ApprovalDecision(
            approved_item_ids=approved_ids,
            high_risk_confirmed_ids=confirmed,
            high_risk_unanswered_ids=unanswered,
        )

    @staticmethod
    def _confirmed_high(high_risk_response, high_ids: set[str]) -> set[str]:
        """Confirmação de high-risk só via sinal explícito por item_id:
        high_risk_response == {"__confirm_high__": [item_id, ...]} (normalizado pelo caller)."""
        if isinstance(high_risk_response, dict):
            ids = set(high_risk_response.get("__confirm_high__", []))
            return ids & high_ids
        return set()   # default seguro: sem confirmação explícita, nenhum high liberado

    @staticmethod
    def build_high_risk_poll(plan: Plan) -> dict:
        """Bloco poll_multi só com os itens risk=high, para confirmação granular (N2)."""
        highs = [i for i in plan.items if i.risk is RiskLevel.HIGH]
        return {
            "type": "poll_multi",
            "question": f"Confirme os {len(highs)} passo(s) de ALTO RISCO a executar:",
            "question_id": f"{plan.question_id}_highrisk",
            "options": [f"{i.label} [{i.tool}]" for i in highs],
            "min_select": 0, "max_select": len(highs),
            "metadata": {"plan_id": plan.plan_id, "item_ids": [i.item_id for i in highs]},
        }
```

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR** do portão de aprovação do marketing: "sem seleção e sem confirmação ⇒ não executa, re-emite poll"; `poll_multi` correlacionado por `question_id`; persistir a mensagem/poll **antes de qualquer yield**.
- **ADAPTAR**: **N2 — segundo poll dedicado para `risk=high`** (que o marketing não tem); "aprovar todos" jamais cobre high-risk; distinção confirmado vs unanswered vs rejeitado (§1.11); uma linha de auditoria por aprovação.
- **EVITAR**: substrings frágeis de confirmação verbal cobrindo high-risk; "aprovar plano vazio faz return cedo, run nunca completa"; registros de aprovação duplicados com `run_id=NULL`.

### §3.6. `PlanExecutor` — guarded transitions, enforcement no try, reconciliação de órfãos

**Fixes embutidos:** §1.7 (`assert_allowed` **dentro** do try por-item → violação vira item `ERROR`, não aborta o plano); §1.8 (`_final_status` usa `required`); §1.11 (high-risk unanswered ≠ rejeitado); §2.5 (reconciliação de itens órfãos em `EXECUTING`).

```python
# app/dev_agent/plan/executor.py
from __future__ import annotations
from collections.abc import AsyncIterator
from app.dev_agent.models.plan import (
    Plan, PlanItem, ItemStatus, PlanStatus, RiskLevel, ItemResult,
)
from app.dev_agent.plan.approval import ApprovalDecision
from app.dev_agent.capability import CapabilityAuthority, CapabilityViolation
from app.dev_agent.gateway.client import GatewayToolClient, GatewayError
from app.dev_agent.plan.repository import PlanRepository
from app.dev_agent.security.redaction import redact_for_store


class PlanExecutor:
    def __init__(self, *, repo: PlanRepository, gateway: GatewayToolClient,
                 authority: CapabilityAuthority) -> None:
        self._repo = repo
        self._gateway = gateway
        self._authority = authority          # §2.4 — MESMA autoridade do guard das personas

    async def execute(self, plan: Plan, decision: ApprovalDecision, *,
                      run_id: str) -> AsyncIterator[ItemResult]:
        # RECONCILIAÇÃO (§2.5 crítica): itens presos em EXECUTING por crash anterior.
        # resume_writes_safe=False (§4) ⇒ WRITE órfão vai a NEEDS_RECONFIRM (nunca replay);
        # READ/low-risk órfão pode voltar a PENDING (re-claim seguro).
        await self._repo.reconcile_orphans(plan.plan_id, executing_ttl_seconds=900)

        moved = await self._repo.transition_plan(
            plan.plan_id, expected=(PlanStatus.PENDING, PlanStatus.APPROVED),
            new=PlanStatus.EXECUTING)
        if not moved:
            plan = await self._repo.load(plan.plan_id)   # outro worker já assumiu / resume

        order = self._ready_order(plan)
        done_task_ids: set[str] = {i.task_id for i in plan.items if i.status is ItemStatus.DONE}
        results: list[ItemResult] = []

        for item in order:
            if item.status is ItemStatus.DONE:
                continue    # RESUME: pula concluídos
            if item.status is ItemStatus.NEEDS_RECONFIRM:
                # WRITE órfão do resume: não executa; sinaliza p/ reconfirmação humana (§4)
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.NEEDS_RECONFIRM,
                               skip_reason="write_orphan_needs_reconfirm")
                results.append(r); yield r
                continue

            # Gate N1
            if item.item_id not in decision.approved_item_ids:
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.PENDING,),
                                                 new=ItemStatus.SKIPPED, error="não aprovado (N1)")
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.SKIPPED, skip_reason="not_approved_n1")
                results.append(r); yield r
                continue

            # Gate N2 — distingue unanswered (§1.11) de rejeitado
            if item.risk is RiskLevel.HIGH and item.item_id not in decision.high_risk_confirmed_ids:
                reason = ("high_risk_unanswered"
                          if item.item_id in decision.high_risk_unanswered_ids
                          else "high_risk_rejected")
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.PENDING,),
                                                 new=ItemStatus.SKIPPED,
                                                 error=f"risk=high não confirmado (N2): {reason}")
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.SKIPPED, skip_reason=reason)
                results.append(r); yield r
                continue

            # Skip encadeado por dependência falha
            if any(dep not in done_task_ids for dep in item.depends_on):
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.PENDING,),
                                                 new=ItemStatus.SKIPPED,
                                                 error="dependência não concluída")
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.SKIPPED, skip_reason="dependency_failed")
                results.append(r); yield r
                continue

            # Claim idempotente: guarded pending/ready -> executing
            claimed = await self._repo.transition_item(
                item.item_id, expected=(ItemStatus.PENDING, ItemStatus.READY),
                new=ItemStatus.EXECUTING)
            if not claimed:
                continue   # outro worker pegou; resume seguro

            # §1.7 crítica: ENFORCEMENT dentro do try por-item — violação vira ERROR, não aborta o plano.
            try:
                self._authority.assert_allowed(
                    profile=item.responsible, capability=item.capability, tool=item.tool)
                result = await self._gateway.call_tool(
                    item.tool, item.input_data,
                    idempotency_key=item.idempotency_key,      # correlação; NÃO dedup do gateway (§4)
                    correlation={"Run-Id": run_id, "Session-Id": plan.session_id,
                                 "Agent-Profile": item.responsible, "Initiated-By": "agent"})
                stored = redact_for_store(item.tool, result)   # §5.3 — segredos NÃO no DB
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.EXECUTING,),
                                                 new=ItemStatus.DONE, output=stored)
                done_task_ids.add(item.task_id)
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.DONE, output=stored)
            except CapabilityViolation as exc:
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.EXECUTING,),
                                                 new=ItemStatus.ERROR, error=f"capability: {exc}")
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.ERROR, error=f"capability: {exc}")
            except GatewayError as exc:
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.EXECUTING,),
                                                 new=ItemStatus.ERROR, error=str(exc)[:2000])
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.ERROR, error=str(exc))
            except Exception as exc:   # não-esperado: item ERROR, plano segue
                await self._repo.transition_item(item.item_id, expected=(ItemStatus.EXECUTING,),
                                                 new=ItemStatus.ERROR, error=str(exc)[:2000])
                r = ItemResult(item_id=item.item_id, task_id=item.task_id, tool=item.tool,
                               status=ItemStatus.ERROR, error=str(exc))
            results.append(r); yield r

        final = self._final_status(plan, results, done_task_ids)
        await self._repo.transition_plan(plan.plan_id, expected=(PlanStatus.EXECUTING,), new=final)

    @staticmethod
    def _ready_order(plan: Plan) -> list[PlanItem]:
        return sorted(plan.items, key=lambda i: i.sequence_num)   # topo-sort já materializado

    @staticmethod
    def _final_status(plan: Plan, results, done_task_ids) -> PlanStatus:
        # §1.8 crítica: semântica de `required`.
        done_ids = set(done_task_ids)
        required_failed = any(
            i.required and i.task_id not in done_ids
            and any(r.item_id == i.item_id and r.status is ItemStatus.ERROR for r in results)
            for i in plan.items
        )
        if required_failed:
            return PlanStatus.FAILED
        total = len(plan.items)
        done = len([i for i in plan.items if i.task_id in done_ids])
        if done == total:
            return PlanStatus.DONE
        # há erros/skips, mas nenhum item required falhou → PARTIAL
        return PlanStatus.PARTIAL
```

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR** do loop de execução do marketing + `marketing_client.py`: loop por item (`executing → done/error`), coleta de `results`, status final `done|partial`; retry de rede via tenacity; headers de correlação; timeouts.
- **ADAPTAR**: (1) `MarketingApiClient` (REST) → `GatewayToolClient` (`tools/call`); (2) dispatcher `if/elif por action_type` → **um único `call_tool(item.tool, ...)`**; (3) enforcement **dentro do try** (§1.7); (4) `_final_status` com `required` (§1.8); (5) high-risk unanswered ≠ rejeitado (§1.11); (6) reconciliação de órfãos (§2.5); (7) redaction no store (§5.3).
- **EVITAR**: stubs "Fase C" (`pending_tool_execution`, item `done` sem executar); `except (GatewayError, Exception)` cru que engole `CapabilityViolation` levantada **fora** do try (agora dentro); tool ausente virando `done`/`skipped` silencioso; acesso `dict.get()` × atributo (`item.endpoint`).

### §3.7. `GatewayToolClient` — Streamable HTTP + OAuth

```python
# app/dev_agent/gateway/client.py
from __future__ import annotations
from typing import Any
import httpx

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
    def _with_retry(fn):
        return retry(
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )(fn)
except ImportError:            # tenacity ausente => no-op (mesmo padrão do marketing_client)
    def _with_retry(fn): return fn


class GatewayError(RuntimeError):
    pass


class GatewayToolClient:
    """Cliente Streamable HTTP para o gateway platform-mcp. Invoca tools via tools/call.
    NUNCA fala REST direto com backends."""
    def __init__(self, *, base_url: str, token_provider,
                 connect_timeout: float = 5.0, read_timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token_provider = token_provider
        self._timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout,
                                      write=10.0, pool=read_timeout)

    async def list_tools(self) -> list[dict]:
        return await self._rpc("tools/list", {}, rpc_id="tools/list")

    @_with_retry
    async def call_tool(self, tool: str, arguments: dict[str, Any], *,
                        idempotency_key: str,
                        correlation: dict[str, str] | None = None) -> dict[str, Any]:
        # id JSON-RPC é distinto do Idempotency-Key (§1.9 crítica): correlação != dedup.
        rpc_id = f"call:{idempotency_key}"
        headers = await self._headers(correlation, idempotency_key)
        payload = {"jsonrpc": "2.0", "id": rpc_id,
                   "method": "tools/call",
                   "params": {"name": tool, "arguments": arguments}}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            resp = await c.post(self._base_url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise GatewayError(f"gateway HTTP {resp.status_code} em {tool}: {resp.text[:400]}")
            body = resp.json()
            if "error" in body:
                raise GatewayError(f"gateway RPC error em {tool}: {body['error']}")
            return body.get("result", {})

    async def _rpc(self, method: str, params: dict, *, rpc_id: str) -> Any:
        headers = await self._headers(None, idem=None)
        payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            resp = await c.post(self._base_url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json().get("result", {})

    async def _headers(self, correlation: dict[str, str] | None, idem: str | None) -> dict[str, str]:
        token = await self._token_provider.get_token()   # OAuth 2.1 (client credentials / refresh)
        h = {"Authorization": f"Bearer {token}",
             "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}   # Streamable HTTP
        if idem is not None:
            h["Idempotency-Key"] = idem                          # correlação/futuro (ver §4)
        for k, v in (correlation or {}).items():
            h[f"X-{k}"] = v
        return h
```

### §3.8. `PlanRepository` + DDL Postgres

Diferença crítica vs. marketing: **todas** as transições de status são **guarded** (`WHERE status = ANY(esperados)`), eliminando o TOCTOU de dupla-execução.

```python
# app/dev_agent/plan/repository.py
from __future__ import annotations
from typing import Sequence
from app.dev_agent.models.plan import Plan, PlanStatus, ItemStatus


class PlanRepository:
    def __init__(self, pool) -> None:      # asyncpg pool (Postgres — dialeto real de runtime)
        self._pool = pool

    async def create(self, plan: Plan) -> None:
        """Insere plano + itens numa transação única. status inicial 'pending'."""

    async def load(self, plan_id: str) -> Plan: ...

    async def get_by_question_id(self, question_id: str) -> Plan | None:
        """Resume: correlaciona a resposta do poll ao plano pendente (UNIQUE question_id)."""

    async def transition_plan(self, plan_id: str, *, expected: Sequence[PlanStatus],
                              new: PlanStatus) -> bool:
        """UPDATE ... WHERE plan_id=$1 AND status = ANY($2). Retorna rowcount>0 (guarded)."""

    async def transition_item(self, item_id: str, *, expected: Sequence[ItemStatus],
                              new: ItemStatus, output: dict | None = None,
                              error: str | None = None) -> bool:
        """UPDATE ... WHERE item_id=$1 AND status = ANY($2). Guarded => idempotência real."""

    async def reconcile_orphans(self, plan_id: str, *, executing_ttl_seconds: int) -> None:
        """§2.5/§4 crítica — itens presos em EXECUTING além do TTL:
           - capability=read (resumível) → volta a PENDING (re-claim seguro);
           - capability=write            → vai a NEEDS_RECONFIRM (nunca replay; §4)."""

    async def expire_stale_plans(self, *, ttl_seconds: int) -> int:
        """§5.2 crítica — planos PENDING além do TTL → EXPIRED. Retorna nº expirados."""

    async def record_approval(self, *, plan_id: str, approved_by: str,
                              approved_item_ids: list[str], high_risk_confirmed_ids: list[str],
                              run_id: str, response_value) -> None:
        """UMA linha de auditoria por aprovação (persiste os item_ids de fato)."""
```

```sql
-- migrations Postgres (dialeto REAL de runtime — NÃO MySQL)
CREATE TABLE IF NOT EXISTS dev_plans (
    plan_id          VARCHAR(36)  PRIMARY KEY,
    session_id       VARCHAR(36)  NOT NULL,
    run_id           VARCHAR(36),
    question_id      VARCHAR(64)  NOT NULL UNIQUE,        -- correlação 1:1 com o poll
    runbook_id       VARCHAR(100) NOT NULL,
    runbook_version  VARCHAR(20)  NOT NULL,               -- DAG versionado
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    title            VARCHAR(500) NOT NULL,
    summary          TEXT,
    responsible_profile VARCHAR(50),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dev_plans_session ON dev_plans(session_id);
CREATE INDEX IF NOT EXISTS idx_dev_plans_status  ON dev_plans(status);

CREATE TABLE IF NOT EXISTS dev_plan_items (
    item_id          VARCHAR(36)  PRIMARY KEY,
    plan_id          VARCHAR(36)  NOT NULL REFERENCES dev_plans(plan_id) ON DELETE CASCADE,
    sequence_num     INT          NOT NULL DEFAULT 0,
    runbook_id       VARCHAR(100) NOT NULL,
    task_id          VARCHAR(100) NOT NULL,
    depends_on       JSONB        NOT NULL DEFAULT '[]',
    tool             VARCHAR(200) NOT NULL,               -- "<namespace>.<operationId>"
    capability       VARCHAR(10)  NOT NULL,               -- read | write
    risk             VARCHAR(10)  NOT NULL DEFAULT 'low',
    required         BOOLEAN      NOT NULL DEFAULT TRUE,   -- §1.8 — usado no _final_status
    label            VARCHAR(500) NOT NULL,
    description      TEXT,
    responsible      VARCHAR(50)  NOT NULL,
    input_json       JSONB        NOT NULL DEFAULT '{}',
    idempotency_key  VARCHAR(64)  NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    output_json      JSONB,
    error_text       TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (plan_id, task_id),                            -- 1 item por task no DAG
    UNIQUE (idempotency_key)                              -- correlação; ver §4
);
CREATE INDEX IF NOT EXISTS idx_dev_plan_items_plan   ON dev_plan_items(plan_id);
CREATE INDEX IF NOT EXISTS idx_dev_plan_items_status ON dev_plan_items(status);

CREATE TABLE IF NOT EXISTS dev_plan_approvals (
    approval_id      VARCHAR(36)  PRIMARY KEY,
    plan_id          VARCHAR(36)  NOT NULL REFERENCES dev_plans(plan_id) ON DELETE CASCADE,
    run_id           VARCHAR(36),
    approved_by      VARCHAR(100) NOT NULL,
    approved_item_ids     JSONB   NOT NULL,               -- persistido de verdade
    high_risk_confirmed   JSONB   NOT NULL DEFAULT '[]',
    response_value        JSONB,
    approved_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

#### COPIAR vs ADAPTAR vs EVITAR

- **COPIAR** de `plans.py` + `orchestrator.py`: `create_plan` item por item; `question_id` UNIQUE; `get_by_question_id`; resume por correlação `response_to_question_id`; o `update_guarded(expected_status=...)` de `creation_flows.py` — aqui **generalizado para o caminho de plano**.
- **ADAPTAR**: (1) DDL **Postgres** desde o início; (2) **guarded transitions em TODAS** as mudanças de status de plano *e* item; (3) `UNIQUE(idempotency_key)` + `UNIQUE(plan_id, task_id)`; (4) coluna `required`; (5) `reconcile_orphans` + `expire_stale_plans`; (6) **uma** linha de auditoria por aprovação.
- **EVITAR**: UPDATE incondicional de status; tabela de aprovação criada fora de migration; `create` + `record_approval` redundantes com `run_id=NULL`; divergência de dialeto SQL; typo `SCHEMA_VERSION="mka_schemka_version"`.

---

## §4. Idempotência & Resume

### Achado verificado do gateway platform-mcp

Investigação do gateway confirmou o comportamento real de idempotência, que **contradiz** a suposição implícita do design P2 (que assumia dedup de write via `Idempotency-Key` do cliente):

- **O gateway NÃO deduplica o efeito de um write pela `Idempotency-Key` enviada pelo cliente.** Ele apenas evita **retentar** writes: `is_idempotent(entry)` faz o retry de rede **apenas para reads**; para writes, `attempts=1` (uma única tentativa, sem replay automático).
- O `_idempotency_key` interno do gateway é usado **somente** para o checkpoint HILT (Human-In-The-Loop) de governança — não é um mecanismo de dedup de efeito de write voltado ao cliente.

**Consequência travada no design:**

- **`resume_writes_safe = False` por padrão.** O design **não depende** de dedup do gateway. Reenviar o mesmo `item.idempotency_key` num resume **não** é garantia de que o write não será duplicado no backend.
- No resume, um item de **WRITE** preso em `EXECUTING` vai para o estado **`NEEDS_RECONFIRM`** — **nunca** replay silencioso. Só um humano reconfirma que o write deve (ou não) ser reexecutado. Isto cobre o caso em que o processo morreu entre o `call_tool` (que já pode ter efetivado o write no backend) e o `transition_item(DONE)` (que não gravou).
- Apenas itens de **READ / low-risk** presos em `EXECUTING` são **resumíveis automaticamente**: `reconcile_orphans` os devolve a `PENDING` para re-claim seguro (read é idempotente por natureza).
- O `GatewayToolClient` **ainda envia** `Idempotency-Key` (para correlação e para uma eventual dedup futura do gateway), mas **o design não conta com ela** para segurança de resume. O `id` do JSON-RPC é distinto da `Idempotency-Key` (§1.9 crítica): `id = "call:<idempotency_key>"` (correlação de request/response) vs header `Idempotency-Key` (marcador de dedup/futuro).

### Política de resume

1. Mensagem chega com `response_to_question_id` → `get_by_question_id(...)`.
2. Se `status == pending` → `ApprovalGate` → `PlanExecutor`. Plano em `executing`/`done`/`expired` **não** é re-executado (guard por status).
3. `PlanExecutor.execute()` chama `reconcile_orphans(executing_ttl_seconds=900)` **antes** de assumir o plano:
   - item `read` órfão em `EXECUTING` além do TTL → `PENDING` (re-claim).
   - item `write` órfão em `EXECUTING` além do TTL → `NEEDS_RECONFIRM` (bloqueia execução automática; sinaliza ao humano via `ItemResult(status=NEEDS_RECONFIRM)`).
4. Itens `DONE` são pulados; a guarda por `expected` em `transition_item` garante que dois workers não executem o mesmo item.

Sem a reconciliação, um item preso em `EXECUTING` por crash **nunca** casaria com `expected=(PENDING, READY)` e ficaria preso para sempre (o "expected não casa" da §2.5 da crítica).

---

## §5. Segurança da execução autônoma

### §5.1. Tetos por-run (tokens/custo, wall-clock, tool-calls)

**Fix da revisão §2.1/§2.2 embutido:** `max_iterations` é por-perfil, mas não protege o custo total. Introduz-se um `RunBudget` por run, consultado no `astream` das personas e no executor:

```python
# app/dev_agent/budget.py (contrato)
from dataclasses import dataclass, field
import time


class BudgetExceeded(RuntimeError):
    """Teto de run estourado — encerra o run de forma limpa (status terminal)."""


@dataclass
class RunBudget:
    max_tokens: int
    max_cost_usd: float
    max_wall_clock_s: float
    max_tool_calls: int
    _tokens: int = 0
    _cost: float = 0.0
    _tool_calls: int = 0
    _started_at: float = field(default_factory=time.monotonic)

    @classmethod
    def for_run(cls, run_id: str) -> "RunBudget":
        # valores de settings; um budget por run
        ...

    def check(self) -> None:
        if self._tokens > self.max_tokens or self._cost > self.max_cost_usd:
            raise BudgetExceeded("teto de tokens/custo do run")
        if (time.monotonic() - self._started_at) > self.max_wall_clock_s:
            raise BudgetExceeded("teto de wall-clock do run")
        if self._tool_calls > self.max_tool_calls:
            raise BudgetExceeded("teto de tool-calls do run")

    def add_usage(self, message) -> None: ...   # acumula tokens/custo do turn
    def count_tool_call(self) -> None:
        self._tool_calls += 1
        self.check()
```

Além disso, o `PlanBuilder` aplica `MAX_ITEMS_PER_PLAN` (§3.4) para evitar plano gigante (fan-out).

### §5.2. TTL de aprovação → estado `EXPIRED`

**Fix da revisão §2.4 embutido:** um plano `PENDING` sem resposta humana não pode ficar pendurado para sempre. `PlanRepository.expire_stale_plans(ttl_seconds=...)` (rodado por scheduler/varredura) transiciona planos `PENDING` além do TTL para **`EXPIRED`**, liberando correlação e limpando estado. O caminho de execução também trata `EXPIRED` como terminal (não executa).

O gate N2 distingue **"pulado por escolha"** de **"pulado por falta de resposta"** (§1.11): high-risk não confirmado gera `skip_reason="high_risk_unanswered"`, sinalizado ao humano — um `destroy_infrastructure` que era o objetivo não é silenciosamente pulado como se rejeitado.

### §5.3. Redaction de segredos

**Fix da revisão §2.7 embutido:** tools do gateway podem devolver segredos (`config-mcp.get_secret`, `auth-mcp.create_jwt`, `config-mcp.list_secrets`, etc.). O output bruto **nunca** vai cru para o DB nem é reinjetado no contexto do LLM.

```python
# app/dev_agent/security/redaction.py (contrato)
# Tools cujo output é sensível por natureza — redação total do payload de retorno.
_SECRET_TOOLS = {
    "config-mcp.get_secret", "config-mcp.list_secrets", "config-mcp.set_secret",
    "config-mcp.rotate_secrets", "auth-mcp.create_jwt", "auth-mcp.create_api_key",
    "auth-mcp.refresh_token",
}
# Chaves cujo valor é sempre mascarado, em qualquer tool.
_SECRET_KEYS = ("token", "secret", "password", "api_key", "jwt", "authorization", "credential")

def redact_for_store(tool: str, result) -> dict:
    """Antes de persistir no DB (output_json)."""
    ...

def redact_for_llm(tool: str, result) -> object:
    """Antes de reinjetar no contexto do LLM (ToolMessage do astream)."""
    ...
```

`redact_for_store` é chamado no `PlanExecutor` antes de `transition_item(DONE, output=...)`; `redact_for_llm` é chamado no `astream` antes de montar o `ToolMessage`.

### §5.4. High-risk (derivação robusta)

Reforço do §3.2: `risk=high` deriva de `operation == MUTATION AND owner in {deploy-mcp, infra-mcp, pipeline-mcp}` como default (com override), **não** de allow-list nominal. Tools destrutivas (`push_acr`, `push_to_registry`, `merge_branch`, `destroy_infrastructure`, `trigger_workflow`, `tag_release`) caem em high por serem mutation de owner sensível — não podem escapar por não estarem num set literal.

### §5.5. Limitação conhecida — concorrência entre planos

Guarded transitions protegem **um** plano de dois workers, mas **não** dois planos distintos agindo no mesmo recurso (ex. dois `create_deployment` no mesmo serviço). Fora de escopo do walking skeleton; registrado como limitação conhecida a endereçar com lock por recurso.

---

## §6. Walking skeleton (ordem de build)

Objetivo: um único runbook read-only executando ponta-a-ponta, sem aprovação, sem write. Prova transporte + persistência + loop. Personas/`astream`/leader ficam **fora** do primeiro E2E.

1. **`config.py` + `models/plan.py`** (Plan/PlanItem/ItemResult tipados, package root único). Só os enums de capability/risk, sem lógica ainda.
2. **`GatewayToolClient.call_tool` contra UMA tool read real** — ex. `services-mcp.check_health` ou `qa-mcp.run_tests`. Provar OAuth + Streamable HTTP + parse de `result` **isolado, num teste de integração**, antes de qualquer orquestração.
3. **`RunbookCatalog` com 1 runbook linear read-only** (2–3 tasks): ex. `check_health → run_tests → generate_report`. + `topological_order` + teste de ciclo.
4. **`PlanBuilder.build_from_runbook`** gerando `Plan` com itens read (cap derivada, risk=low). Validar `input_schema`.
5. **`PlanRepository`** (Postgres) com `transition_plan`/`transition_item` **guarded**. Testar a guarda (`expected≠atual` → no-op) e `reconcile_orphans`.
6. **`PlanExecutor.execute`** sem aprovação (todos aprovados, zero high-risk): itera a ordem, chama gateway, grava `DONE`, fecha o plano. **Primeiro "autônomo E2E".**
7. **Só então** ligar, nesta ordem: `CapabilityAuthority` (enforcement ON), `ApprovalGate` N1, e por último N2 high-risk + `RunbookSelector` + orquestrador/dispatch completo + personas ReAct (segundo E2E) + `RunBudget` + redaction.

---

## §7. Checklist de testes antes de "sem humano"

**Bloqueadores (sem estes, não roda autônomo):**

- [ ] **Idempotência real:** executar o mesmo item 2× com o mesmo `idempotency_key` e observar o efeito no backend. Como o gateway **não deduplica writes** (§4), o teste prova que o resume de write está **proibido** (write órfão → `NEEDS_RECONFIRM`).
- [ ] **Resume após crash:** matar o processo entre `call_tool`-OK e `transition_item(DONE)`; provar que write órfão vai a `NEEDS_RECONFIRM` (não replay) e read órfão volta a `PENDING` (re-claim). Testar item preso em `EXECUTING`.
- [ ] **Guarded transition sob corrida:** dois executores no mesmo plano/item → exatamente um executa.
- [ ] **Capability enforcement:** persona sem WRITE tentando tool write → `CapabilityViolation` vira item `ERROR` (dentro do try), **não** aborta o plano nem retorna sucesso falso.
- [ ] **DAG:** ciclo, `depends_on` órfão, e **skip encadeado** (dep falha → dependentes `SKIPPED`, nunca executam com input vazio).

**Segurança/liveness:**

- [ ] **Gate N2:** high-risk nunca executa por "aprovar todos" nem por confirmação verbal; só por poll dedicado com `item_id`.
- [ ] **Unanswered vs rejeitado (§1.11):** high-risk não confirmado gera `skip_reason="high_risk_unanswered"` sinalizado, não some silenciosamente.
- [ ] **TTL de aprovação:** plano `PENDING` não respondido expira para `EXPIRED`, não fica pendurado.
- [ ] **Tetos por-run:** teto de tokens/custo, wall-clock e tool-calls dispara `BudgetExceeded` e encerra o run com status terminal.
- [ ] **Redaction:** output de `get_secret`/`create_jwt` não aparece no DB (`output_json`) nem no contexto do LLM (`ToolMessage`).

**Regressão dos gotchas herdados:**

- [ ] `TasksRepository` grava de fato (kwargs corretos) — assert de **linha no DB**, não só ausência de exceção.
- [ ] Flush final SEMPRE (inclusive caminho "não aprovado"/plano vazio) — run nunca fica sem status terminal.
- [ ] `confidence < 0.6` cai em `architecture` **em Python** (teste com LLM devolvendo 0.5).
- [ ] `_final_status` com semântica de `required`: item required com ERROR → `FAILED`; opcional com ERROR → `PARTIAL`.

---

## §8. Anti-regressão (o que NÃO herdar do marketing-agent)

1. **Sem stubs "Fase C"** — nenhum `pending_tool_execution`; tool ausente ⇒ item `ERROR`, nunca `DONE` falso.
2. **Sem if/elif monolítico** por `action_type` — dispatch table + um único `call_tool(item.tool, ...)`.
3. **Sem LangGraph paralelo morto** — não portar `graph/nodes.py`/`route_intent`.
4. **Sem `_CIRCUIT_BREAKER_THRESHOLD` inerte** — se quiser circuit-breaker, implementá-lo de fato.
5. **Enforcement ON** — capability por verbo, **autoridade única** (§2.4) consumida pelos dois caminhos (guard-persona e enforcer-executor); nunca opt-in.
6. **Transporte único**: só gateway platform-mcp (Streamable HTTP + OAuth). Sem REST, sem import in-process.
7. **Guarded transitions em plano E item** — elimina TOCTOU/dupla-execução.
8. **DDL Postgres versionado** desde o início (sem divergência de dialeto; sem tabela fora de migration).
9. **Uma linha de auditoria** por aprovação, persistindo `approved_item_ids` e `high_risk_confirmed`.
10. **DAG com topo-sort + detecção de ciclo** — não apenas declarativo.
11. **Plano nasce do runbook versionado** (via `RunbookSelector` com enum fechado), não de LLM livre com fallback `"generic"`.
12. **Sem bug de kwargs em `tasks_repo`** — call-site e assinatura alinhados (`input_json`/`output_text`/`error_text`).
13. **`max_iterations` real** por-perfil — sem setting fantasma efetivo em 10.
14. **`confidence` enforced em Python** — não só no prompt.
15. **Cache de intenção com bound** — LRU + TTL, não dict de classe crescendo sem limite.
16. **`_StepContext` completo** — `run_id`/`message_id`/`text_chunk` sempre presentes (senão nenhuma task grava).
17. **Idempotência não presumida do gateway** (§4) — resume de write proibido; write órfão → `NEEDS_RECONFIRM`.
18. **Redaction de segredos** antes de persistir e antes de reinjetar no LLM.

---

### Notas de referência (arquivos-fonte do marketing usados como base)

Padrão Plan-Approve-Execute e schemas em `platform-marketing-agent/app/modules/marketing_agent/models/plan.py` e `orchestrator.py`; retry/timeout de rede em `app/infrastructure/http/marketing_client.py`; guarded update em `app/infrastructure/db/repositories/creation_flows.py`; persistência de plano em `app/infrastructure/db/repositories/plans.py`; runbook DAG declarativo e fonte única de tools em `platform-marketing/src/markai_shared/runbook_catalog.py` e `src/markai_contracts/tool_matrix.py`.
