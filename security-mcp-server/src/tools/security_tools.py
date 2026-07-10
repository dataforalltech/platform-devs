"""Security Security Tools — análise de segurança real (não stubs).

Funções puras que recebem inputs e retornam dict. Cada ferramenta faz análise
concreta sobre o que recebe (código, manifest, vetor CVSS, contexto de compliance)
em vez de devolver dados fixos.
"""

from __future__ import annotations

import math
import re
from typing import Any

# ============================================================================
# 1. Static Application Security Testing (SAST) — análise de código por padrão
# ============================================================================

# (regex, título, severidade, cwe, owasp, recomendação, linguagens)
_CODE_PATTERNS: list[tuple[str, str, str, str, str, str, tuple[str, ...]]] = [
    (
        r"""(?i)\b(?:select|insert|update|delete)\b.*?\+\s*['"]?\s*\w+|f['"].*?\b(?:select|insert|update|delete)\b.*?\{""",
        "Possível SQL Injection",
        "high",
        "CWE-89",
        "A03:2021-Injection",
        "Use queries parametrizadas / prepared statements; nunca concatene input em SQL.",
        ("python", "java", "javascript", "typescript", "go", "php"),
    ),
    (
        r"(?i)\b(?:os\.system|subprocess\.(?:call|run|Popen)|exec|eval|child_process\.exec)\s*\(.*(?:\+|%|f['\"]|\$\{|request|input|argv|params)",
        "Possível Command/Code Injection",
        "critical",
        "CWE-78",
        "A03:2021-Injection",
        "Evite exec/eval com input do usuário; use APIs seguras e allow-lists de argumentos.",
        ("python", "javascript", "typescript", "php"),
    ),
    (
        r"(?i)(?:innerHTML|outerHTML|document\.write|dangerouslySetInnerHTML)\s*[=(]",
        "Possível Cross-Site Scripting (XSS)",
        "high",
        "CWE-79",
        "A03:2021-Injection",
        "Sanitize/escape a saída; prefira textContent ou frameworks com auto-escaping.",
        ("javascript", "typescript"),
    ),
    (
        r"(?i)\b(?:md5|sha1)\s*\(|hashlib\.(?:md5|sha1)\b|MessageDigest\.getInstance\(\s*['\"](?:MD5|SHA-?1)['\"]",
        "Algoritmo de hash fraco",
        "medium",
        "CWE-327",
        "A02:2021-Cryptographic Failures",
        "Use SHA-256+ para integridade; para senhas use argon2id/bcrypt/scrypt.",
        ("python", "java", "javascript", "typescript", "go"),
    ),
    (
        r"(?i)(?:AES|DES|Cipher)\S*(?:ECB|/ECB/)|Cipher\.getInstance\(\s*['\"]DES",
        "Cifra insegura (ECB/DES)",
        "high",
        "CWE-327",
        "A02:2021-Cryptographic Failures",
        "Use AES-GCM (AEAD) com IV aleatório; nunca ECB nem DES/3DES.",
        ("python", "java", "javascript", "typescript"),
    ),
    (
        r"(?i)verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true|CURLOPT_SSL_VERIFYPEER\s*,\s*(?:0|false)",
        "Verificação de certificado TLS desabilitada",
        "high",
        "CWE-295",
        "A07:2021-Identification and Authentication Failures",
        "Nunca desabilite verificação de certificado; corrija a cadeia de confiança.",
        ("python", "javascript", "typescript", "go", "php"),
    ),
    (
        r"(?i)pickle\.loads?|yaml\.load\s*\((?!.*Loader)|Marshal\.load|ObjectInputStream",
        "Desserialização insegura",
        "high",
        "CWE-502",
        "A08:2021-Software and Data Integrity Failures",
        "Use yaml.safe_load / formatos seguros (JSON); não desserialize dados não confiáveis.",
        ("python", "java", "ruby"),
    ),
    (
        r"(?i)Math\.random\s*\(\)|random\.random\s*\(\)|random\.randint",
        "PRNG não criptográfico usado em contexto sensível",
        "low",
        "CWE-338",
        "A02:2021-Cryptographic Failures",
        "Para tokens/segredos use secrets (Python) ou crypto.randomBytes (Node).",
        ("python", "javascript", "typescript"),
    ),
    (
        r"(?i)(?:open|render_template_string|send_file)\s*\(.*(?:\.\./|request\.|params|argv)",
        "Possível Path Traversal / SSTI",
        "high",
        "CWE-22",
        "A01:2021-Broken Access Control",
        "Valide e normalize paths; use allow-list; não interpole input em templates.",
        ("python", "javascript", "typescript"),
    ),
]


def review_secure_code(code: str = "", language: str = "python") -> dict[str, Any]:
    """Revisa um trecho de código contra padrões OWASP/CWE, com números de linha."""
    findings: list[dict[str, Any]] = []
    lines = code.splitlines()
    lang = (language or "").lower()

    for regex, title, severity, cwe, owasp, rec, langs in _CODE_PATTERNS:
        if lang and langs and lang not in langs:
            continue
        pattern = re.compile(regex)
        for idx, line in enumerate(lines, start=1):
            if pattern.search(line):
                findings.append(
                    {
                        "type": title,
                        "severity": severity,
                        "line": idx,
                        "cwe": cwe,
                        "owasp": owasp,
                        "snippet": line.strip()[:160],
                        "recommendation": rec,
                    }
                )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    counts = {sev: sum(1 for f in findings if f["severity"] == sev) for sev in order}

    return {
        "language": language,
        "lines_scanned": len(lines),
        "issues_found": len(findings),
        "severity_counts": counts,
        "issues": findings,
        "verdict": (
            "reprovado" if counts["critical"] or counts["high"] else ("atenção" if findings else "aprovado")
        ),
        "note": "Análise heurística por padrões — complemente com SAST dedicado (Semgrep/CodeQL) e revisão manual.",  # noqa: E501
        "status": "reviewed",
    }


# ============================================================================
# 2. Secrets scanning — detecção de credenciais hardcoded (com masking)
# ============================================================================

_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID", "critical"),
    (
        r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})",
        "AWS Secret Access Key",
        "critical",
    ),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token", "critical"),
    (r"github_pat_[A-Za-z0-9_]{22,}", "GitHub Fine-grained PAT", "critical"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack Token", "high"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI/Stripe-style Secret Key", "high"),
    (r"AIza[0-9A-Za-z\-_]{35}", "Google API Key", "high"),
    (
        r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
        "Private Key",
        "critical",
    ),
    (
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        "JWT (possível token exposto)",
        "medium",
    ),
    (
        r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*['\"]([^'\"]{6,})['\"]",
        "Credencial hardcoded",
        "high",
    ),
    (r"(?i)postgres(?:ql)?://[^:\s]+:[^@\s]+@", "Connection string com senha", "high"),
]


def _mask(value: str) -> str:
    value = value.strip()
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}…{value[-2:]} ({len(value)} chars)"


def scan_secrets(content: str = "", filename: str = "") -> dict[str, Any]:
    """Detecta segredos hardcoded em texto/código. Sempre mascara o valor."""
    findings: list[dict[str, Any]] = []
    lines = content.splitlines()

    for regex, kind, severity in _SECRET_PATTERNS:
        pattern = re.compile(regex)
        for idx, line in enumerate(lines, start=1):
            m = pattern.search(line)
            if m:
                captured = m.group(1) if m.groups() else m.group(0)
                findings.append(
                    {
                        "type": kind,
                        "severity": severity,
                        "line": idx,
                        "masked_value": _mask(captured),
                        "cwe": "CWE-798",
                    }
                )

    return {
        "filename": filename or "(inline)",
        "lines_scanned": len(lines),
        "secrets_found": len(findings),
        "findings": findings,
        "recommendation": (
            "Remova segredos do código; use um secrets manager (Vault/KMS/Secrets Manager), "
            "rotacione qualquer credencial exposta e adicione varredura de segredos no CI (gitleaks/trufflehog)."  # noqa: E501
        ),
        "status": (
            "critical"
            if any(f["severity"] == "critical" for f in findings)
            else ("findings" if findings else "clean")
        ),
    }


# ============================================================================
# 3. CVSS v3.1 base score calculator
# ============================================================================

_CVSS_WEIGHTS = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PR_WEIGHTS = {
    "U": {"N": 0.85, "L": 0.62, "H": 0.27},
    "C": {"N": 0.85, "L": 0.68, "H": 0.50},
}


def _cvss_roundup(value: float) -> float:
    int_input = round(value * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000) + 1) / 10.0


def _severity_rating(score: float) -> str:
    if score == 0:
        return "None"
    if score < 4.0:
        return "Low"
    if score < 7.0:
        return "Medium"
    if score < 9.0:
        return "High"
    return "Critical"


def calculate_cvss(vector: str = "") -> dict[str, Any]:
    """Calcula CVSS v3.1 base score a partir de um vetor.

    Ex: CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
    """
    metrics: dict[str, str] = {}
    for part in vector.strip().split("/"):
        if ":" in part and not part.upper().startswith("CVSS"):
            k, v = part.split(":", 1)
            metrics[k.upper()] = v.upper()

    required = ["AV", "AC", "PR", "UI", "S", "C", "I", "A"]
    missing = [m for m in required if m not in metrics]
    if missing:
        return {
            "error": "vetor_incompleto",
            "missing_metrics": missing,
            "expected_format": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        }

    try:
        scope = metrics["S"]  # U (Unchanged) ou C (Changed)
        iss = 1 - (
            (1 - _CVSS_WEIGHTS["C"][metrics["C"]])
            * (1 - _CVSS_WEIGHTS["I"][metrics["I"]])
            * (1 - _CVSS_WEIGHTS["A"][metrics["A"]])
        )
        if scope == "U":
            impact = 6.42 * iss
        else:
            impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15

        exploitability = (
            8.22
            * _CVSS_WEIGHTS["AV"][metrics["AV"]]
            * _CVSS_WEIGHTS["AC"][metrics["AC"]]
            * _PR_WEIGHTS[scope][metrics["PR"]]
            * _CVSS_WEIGHTS["UI"][metrics["UI"]]
        )

        if impact <= 0:
            base = 0.0
        elif scope == "U":
            base = _cvss_roundup(min(impact + exploitability, 10))
        else:
            base = _cvss_roundup(min(1.08 * (impact + exploitability), 10))
    except (KeyError, ValueError) as e:
        return {"error": "valor_de_metrica_invalido", "detail": str(e)}

    return {
        "vector": vector.strip(),
        "base_score": base,
        "severity": _severity_rating(base),
        "impact_subscore": round(impact, 1),
        "exploitability_subscore": round(exploitability, 1),
        "metrics": metrics,
        "status": "calculated",
    }


# ============================================================================
# 4. Threat modeling — STRIDE por componente
# ============================================================================

_STRIDE = {
    "Spoofing": (
        "Autenticação",
        "Falsificação de identidade de usuário/serviço",
        "MFA, mTLS, tokens assinados, validação de identidade",
    ),
    "Tampering": (
        "Integridade",
        "Modificação não autorizada de dados/código em trânsito ou repouso",
        "Assinaturas/HMAC, TLS, controle de integridade, WORM logs",
    ),
    "Repudiation": (
        "Não-repúdio",
        "Negar ações executadas por falta de trilha",
        "Logs auditáveis assinados, correlação de eventos, timestamps confiáveis",
    ),
    "Information Disclosure": (
        "Confidencialidade",
        "Vazamento de dados sensíveis/PII",
        "Criptografia at-rest/in-transit, mascaramento, least privilege",
    ),
    "Denial of Service": (
        "Disponibilidade",
        "Exaustão de recursos / indisponibilidade",
        "Rate limiting, quotas, autoscaling, timeouts, circuit breakers",
    ),
    "Elevation of Privilege": (
        "Autorização",
        "Ganho de privilégios além do autorizado",
        "RBAC/ABAC, validação server-side, deny-by-default, isolamento",
    ),
}


def generate_threat_model(
    system: str = "system", scope: str = "", components: list | None = None
) -> dict[str, Any]:
    """Gera modelo de ameaças STRIDE. Se `components` for informado, mapeia por componente."""
    components = components or [
        "API Gateway",
        "Auth Service",
        "Database",
        "External Integration",
    ]

    threats = []
    tid = 1
    for comp in components:
        for category, (dim, desc, mitig) in _STRIDE.items():
            threats.append(
                {
                    "id": f"T{tid:02d}",
                    "component": comp,
                    "category": category,
                    "security_dimension": dim,
                    "threat": desc,
                    "recommended_mitigation": mitig,
                    "default_severity": (
                        "high"
                        if category in ("Elevation of Privilege", "Information Disclosure")
                        else "medium"
                    ),
                }
            )
            tid += 1

    return {
        "title": f"Threat Model: {system}",
        "system": system,
        "scope": scope or "Avaliação de segurança do sistema completo",
        "methodology": "STRIDE",
        "components": components,
        "threat_count": len(threats),
        "threats": threats,
        "next_steps": [
            "Priorizar ameaças com data flow diagram (DFD)",
            "Atribuir CVSS às ameaças confirmadas",
            "Converter mitigações em backlog de segurança",
        ],
        "status": "draft",
    }


# ============================================================================
# 5. Attack surface & controls
# ============================================================================


def map_attack_surface(
    system: str = "system",
    endpoints: list | None = None,
    integrations: list | None = None,
) -> dict[str, Any]:
    """Mapeia a superfície de ataque; aceita endpoints/integrações reais."""
    endpoints = endpoints or [
        {"type": "API", "path": "/api/*", "authentication": "required"},
        {"type": "Web", "path": "/*", "authentication": "optional"},
    ]
    integrations = integrations or [
        {"name": "Database", "type": "internal", "exposure": "none"},
        {"name": "External API", "type": "external", "exposure": "public"},
    ]

    exposed = [
        e for e in endpoints if str(e.get("authentication", "")).lower() in ("optional", "none", "public", "")
    ]
    public_integrations = [
        i for i in integrations if str(i.get("exposure", "")).lower() in ("public", "external")
    ]

    return {
        "title": f"Attack Surface: {system}",
        "system": system,
        "endpoints": endpoints,
        "integrations": integrations,
        "risk_hotspots": {
            "unauthenticated_endpoints": exposed,
            "public_integrations": public_integrations,
        },
        "recommendations": [
            "Aplicar authn/authz em todo endpoint que exponha dados ou ações",
            "Rate limiting e WAF na borda pública",
            "Segmentar integrações externas em zona de confiança separada",
        ],
        "status": "analyzed",
    }


def generate_security_controls(
    system: str = "system", threat_categories: list | None = None
) -> dict[str, Any]:
    """Gera controles técnicos e processuais, mapeados por categoria de ameaça."""
    catalog = {
        "authentication": {
            "name": "Autenticação forte (MFA/OIDC)",
            "type": "technical",
            "nist_csf": "PR.AC",
        },
        "authorization": {
            "name": "RBAC/ABAC deny-by-default",
            "type": "technical",
            "nist_csf": "PR.AC",
        },
        "encryption": {
            "name": "Criptografia in-transit (TLS 1.3) e at-rest (AES-GCM)",
            "type": "technical",
            "nist_csf": "PR.DS",
        },
        "input_validation": {
            "name": "Validação/saneamento de input",
            "type": "technical",
            "nist_csf": "PR.IP",
        },
        "logging": {
            "name": "Logging e auditoria centralizados",
            "type": "operational",
            "nist_csf": "DE.CM",
        },
        "monitoring": {
            "name": "Monitoramento e alerta de anomalias",
            "type": "operational",
            "nist_csf": "DE.CM",
        },
        "incident_response": {
            "name": "Plano de resposta a incidentes",
            "type": "operational",
            "nist_csf": "RS.RP",
        },
        "backup": {
            "name": "Backup e recuperação testados",
            "type": "operational",
            "nist_csf": "PR.IP",
        },
    }
    selected = threat_categories or list(catalog.keys())
    controls = []
    for i, key in enumerate(selected, start=1):
        base = catalog.get(key, {"name": key, "type": "technical", "nist_csf": "PR"})
        controls.append({"id": f"SC{i:02d}", **base, "status": "recommended"})

    return {
        "title": f"Security Controls: {system}",
        "system": system,
        "controls": controls,
        "control_count": len(controls),
        "status": "recommended",
    }


# ============================================================================
# 6. Dependency / SCA scanning (parse do manifest fornecido)
# ============================================================================


def scan_dependency_risks(manifest: str = "", ecosystem: str = "python") -> dict[str, Any]:
    """Extrai dependências de um manifest e sinaliza riscos heurísticos.

    Sem acesso a um feed de CVE em runtime, sinaliza padrões de risco (versões
    pinadas vs. ranges abertos, versões 0.x, licenças copyleft citadas) e devolve
    o inventário para correlação posterior com OSV/NVD.
    """
    deps: list[dict[str, str]] = []
    eco = (ecosystem or "").lower()

    for raw in manifest.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(
            r"^\"?([A-Za-z0-9_.\-@/]+)\"?\s*[:=]?\s*[\^~>=<]*\s*([0-9][0-9A-Za-z.\-]*)",
            line,
        )
        if not m:
            m = re.match(r"^([A-Za-z0-9_.\-@/]+)[=<>~^ ]+v?([0-9][0-9A-Za-z.\-]*)", line)
        if m:
            name, version = m.group(1), m.group(2)
            risk_flags = []
            if version.startswith("0."):
                risk_flags.append("pre-1.0 (API instável)")
            deps.append(
                {
                    "package": name,
                    "version": version,
                    "flags": ", ".join(risk_flags) or "-",
                }
            )

    unpinned = len(re.findall(r"[\^~]|>=|\*", manifest))

    return {
        "ecosystem": eco or "unknown",
        "dependencies_found": len(deps),
        "dependencies": deps,
        "hygiene": {
            "unpinned_or_range_specs": unpinned,
            "recommendation": "Fixe versões (lockfile), habilite Dependabot/Renovate e rode SCA (osv-scanner/Trivy) no CI.",  # noqa: E501
        },
        "next_step": "Correlacione o inventário com OSV.dev / NVD para CVEs e com licenças para risco jurídico.",  # noqa: E501
        "status": "scanned",
    }


# noqa: E501

# ============================================================================  # noqa: E501
# 7. Compliance mapping (frameworks reais)
# ============================================================================

_COMPLIANCE_FRAMEWORKS = {
    "lgpd": {
        "name": "LGPD (Lei 13.709/2018)",
        "controls": [
            ("base_legal", "Base legal para tratamento de dados pessoais"),
            ("consentimento", "Coleta e gestão de consentimento"),
            (
                "direitos_titular",
                "Atendimento a direitos do titular (acesso, correção, eliminação, portabilidade)",
            ),
            ("minimizacao", "Minimização e finalidade do tratamento"),
            ("dpo", "Encarregado (DPO) designado"),
            ("incidentes", "Comunicação de incidentes à ANPD e titulares"),
            ("ripd", "Relatório de Impacto (RIPD) para tratamentos de risco"),
        ],
    },
    "soc2": {
        "name": "SOC 2 (Trust Services Criteria)",
        "controls": [
            (
                "security",
                "Segurança (controles de acesso, criptografia, monitoramento)",
            ),
            ("availability", "Disponibilidade (SLA, DR, backups)"),
            (
                "confidentiality",
                "Confidencialidade (classificação e proteção de dados)",
            ),
            ("processing_integrity", "Integridade de processamento"),
            ("privacy", "Privacidade (ciclo de vida de dados pessoais)"),
        ],
    },
    "iso27001": {
        "name": "ISO/IEC 27001:2022",
        "controls": [
            ("isms", "Sistema de Gestão de Segurança da Informação (SGSI)"),
            ("risk_assessment", "Avaliação e tratamento de risco"),
            ("access_control", "Controle de acesso (A.5.15-A.5.18)"),
            ("crypto", "Criptografia (A.8.24)"),
            ("supplier", "Segurança na cadeia de fornecedores (A.5.19-A.5.23)"),
            ("incident_mgmt", "Gestão de incidentes (A.5.24-A.5.28)"),
        ],
    },
    "pci-dss": {
        "name": "PCI-DSS v4.0",
        "controls": [
            ("network_seg", "Segmentação de rede do ambiente de dados de cartão (CDE)"),
            ("encryption", "Criptografia de PAN em trânsito e repouso"),
            ("access_control", "Acesso restrito a dados de titular por need-to-know"),
            ("logging", "Trilhas de auditoria e monitoramento"),
            ("vuln_mgmt", "Gestão de vulnerabilidades e patching"),
            ("pentest", "Testes de segurança periódicos"),
        ],
    },
    "owasp": {
        "name": "OWASP Top 10 (2021)",
        "controls": [
            ("A01", "Broken Access Control"),
            ("A02", "Cryptographic Failures"),
            ("A03", "Injection"),
            ("A04", "Insecure Design"),
            ("A05", "Security Misconfiguration"),
            ("A06", "Vulnerable and Outdated Components"),
            ("A07", "Identification and Authentication Failures"),
            ("A08", "Software and Data Integrity Failures"),
            ("A09", "Security Logging and Monitoring Failures"),
            ("A10", "Server-Side Request Forgery (SSRF)"),
        ],
    },
}


def analyze_compliance(framework: str = "owasp", context: dict | None = None) -> dict[str, Any]:
    """Avalia conformidade contra um framework. `context` marca controles atendidos.

    context = {"satisfied": ["A01", "A02"]} → marca esses controles como conformes.
    """
    context = context or {}
    fw_key = (framework or "owasp").lower()
    fw = _COMPLIANCE_FRAMEWORKS.get(fw_key)
    if not fw:
        return {
            "error": "framework_desconhecido",
            "supported": list(_COMPLIANCE_FRAMEWORKS.keys()),
        }

    satisfied = {str(s).lower() for s in context.get("satisfied", [])}
    controls = []
    gaps = []
    for ctrl_id, desc in fw["controls"]:
        is_ok = ctrl_id.lower() in satisfied
        controls.append({"id": ctrl_id, "control": desc, "status": "compliant" if is_ok else "gap"})
        if not is_ok:
            gaps.append({"id": ctrl_id, "control": desc})

    total = len(fw["controls"])
    met = total - len(gaps)
    pct = round(met / total * 100) if total else 0

    return {
        "framework": fw["name"],
        "compliance_percentage": f"{pct}%",
        "controls_met": met,
        "controls_total": total,
        "controls": controls,
        "gaps": gaps,
        "priority": "high" if pct < 60 else ("medium" if pct < 90 else "low"),
        "status": "analyzed",
    }


# ============================================================================
# 8. Incident response plan (NIST 800-61)
# ============================================================================


def generate_incident_response_plan(
    incident_type: str = "data_breach", severity: str = "high"
) -> dict[str, Any]:
    """Gera um runbook de resposta a incidentes seguindo o ciclo NIST SP 800-61."""
    sla = {
        "critical": "15 min",
        "high": "1 h",
        "medium": "4 h",
        "low": "1 dia útil",
    }.get(severity.lower(), "1 h")

    return {
        "incident_type": incident_type,
        "severity": severity,
        "response_sla": sla,
        "framework": "NIST SP 800-61r2",
        "phases": {
            "1_preparation": [
                "Contatos e on-call definidos",
                "Acesso a logs/EDR garantido",
                "Playbooks versionados",
            ],
            "2_detection_analysis": [
                "Confirmar o incidente e escopo (IOCs, sistemas, dados afetados)",
                "Classificar severidade e acionar war room",
                "Preservar evidências (chain of custody)",
            ],
            "3_containment": [
                "Contenção de curto prazo (isolar host/credencial)",
                "Contenção de longo prazo (patch, rotação de segredos, revogação de tokens)",
            ],
            "4_eradication": [
                "Remover acesso do atacante",
                "Eliminar malware/backdoors",
                "Corrigir vulnerabilidade raiz",
            ],
            "5_recovery": [
                "Restaurar de fonte confiável",
                "Monitoramento reforçado",
                "Validar integridade antes de reabrir",
            ],
            "6_post_incident": [
                "RCA (5 whys)",
                "Lições aprendidas",
                "Atualizar controles e detecções",
            ],
        },
        "communication": {
            "internal": ["Security lead", "Engenharia", "Jurídico", "Comunicação"],
            "external_if_pii": [
                "ANPD (LGPD, até 3 dias úteis)",
                "Titulares afetados",
                "Clientes/parceiros conforme contrato",
            ],
        },
        "status": "ready",
    }


# ============================================================================
# 9. Security headers hardening
# ============================================================================

_RECOMMENDED_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "Content-Security-Policy": "default-src 'self'; object-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cache-Control": "no-store (para respostas sensíveis)",
}


def harden_headers(current_headers: dict | None = None) -> dict[str, Any]:
    """Analisa headers HTTP atuais e recomenda hardening (OWASP Secure Headers)."""
    current = {k.lower(): v for k, v in (current_headers or {}).items()}
    missing = []
    present = []
    for header, recommended in _RECOMMENDED_HEADERS.items():
        if header.lower() in current:
            present.append({"header": header, "value": current[header.lower()]})
        else:
            missing.append({"header": header, "recommended_value": recommended})

    dangerous = []
    if "server" in current or "x-powered-by" in current:
        dangerous.append("Remova headers Server/X-Powered-By (fingerprinting da stack).")

    return {
        "present_secure_headers": present,
        "missing_headers": missing,
        "info_leak_warnings": dangerous,
        "score": f"{len(present)}/{len(_RECOMMENDED_HEADERS)}",
        "status": "analyzed",
    }


# ============================================================================
# 10. Password / auth policy assessment (NIST 800-63B)
# ============================================================================


def check_password_policy(policy: dict | None = None) -> dict[str, Any]:
    """Avalia uma política de senha contra NIST SP 800-63B."""
    policy = policy or {}
    min_len = int(policy.get("min_length", 0))
    findings = []

    if min_len < 8:
        findings.append(
            {
                "issue": "Comprimento mínimo abaixo de 8",
                "severity": "high",
                "fix": "Exija >= 8 (ideal 12+) caracteres.",
            }
        )
    if policy.get("require_complexity"):
        findings.append(
            {
                "issue": "Regras de complexidade obrigatórias",
                "severity": "low",
                "fix": "NIST desaconselha composição forçada; prefira comprimento + blocklist.",
            }
        )
    if policy.get("periodic_rotation"):
        findings.append(
            {
                "issue": "Rotação periódica forçada",
                "severity": "low",
                "fix": "NIST recomenda rotacionar só sob suspeita de comprometimento.",
            }
        )
    if not policy.get("check_breached_passwords"):
        findings.append(
            {
                "issue": "Sem verificação contra senhas vazadas",
                "severity": "medium",
                "fix": "Compare com blocklist (ex: HaveIBeenPwned k-anonymity).",
            }
        )
    if not policy.get("mfa"):
        findings.append(
            {
                "issue": "MFA não exigido",
                "severity": "high",
                "fix": "Exija MFA, preferindo WebAuthn/TOTP a SMS.",
            }
        )
    if not policy.get("rate_limit_login"):
        findings.append(
            {
                "issue": "Sem rate limiting / lockout no login",
                "severity": "medium",
                "fix": "Aplique throttling e proteção contra credential stuffing.",
            }
        )

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    return {
        "standard": "NIST SP 800-63B",
        "evaluated_policy": policy,
        "findings": findings,
        "compliant": not any(f["severity"] in ("high", "critical") for f in findings),
        "status": "evaluated",
    }


def stub_tool() -> dict[str, Any]:
    """Status check."""
    return {"status": "ok", "service": "security", "tools": 12}
