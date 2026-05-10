# Knowledge Base MCP — Central Documentation Repository

Centraliza toda a documentação, padrões e referências que os Zillas consultam.

## Propósito

- **Single source of truth** para padrões, frameworks, standards
- **Versionado** com git (history de mudanças)
- **Consultável** via MCP (query API)
- **Estruturado** por domínio (API, Security, Infrastructure, etc.)
- **Atualizado** em real-time pelos Zillas

## Estrutura

```
knowledge-base-mcp/
├── api/
│   ├── standards.md          # REST conventions, error handling
│   ├── contract-examples/    # Sample API contracts
│   └── versioning.md         # API versioning strategy
├── architecture/
│   ├── patterns.md           # Microservices, DDD, C4
│   ├── adr-template.md       # ADR format
│   └── tech-stack.md         # Approved technologies
├── frontend/
│   ├── design-system.md      # Components, tokens, guidelines
│   ├── accessibility.md      # WCAG 2.1 standards
│   └── ui-patterns.md        # Common UI patterns
├── backend/
│   ├── code-style.md         # Python, TypeScript conventions
│   ├── testing-standards.md  # Unit, integration, E2E
│   └── database-patterns.md  # Schema design, queries
├── infrastructure/
│   ├── terraform-modules.md  # Standard modules
│   ├── k8s-patterns.md       # Kubernetes configs
│   └── deployment-guide.md   # Release process
├── security/
│   ├── threat-models.md      # STRIDE, risk assessment
│   ├── owasp-checklist.md    # OWASP Top 10
│   ├── lgpd-compliance.md    # LGPD requirements
│   └── secret-management.md  # Credential handling
├── quality/
│   ├── test-pyramid.md       # Testing strategy
│   ├── coverage-targets.md   # Code coverage goals
│   └── test-data.md          # Test data management
└── platform/
    ├── ecosystem.yaml        # Service registry
    ├── AGENTS.md             # Trinity Pattern + responsibilities
    ├── roadmap.md            # Product roadmap
    └── team-structure.md     # Teams + ownership
```

## Tools (MCP)

- `search_knowledge_base(query, domain?)` — Full-text search
- `get_document(path)` — Fetch specific document
- `list_domain(domain)` — List all docs in a domain
- `get_approved_technologies()` — Tech stack whitelist
- `get_api_standards()` — API design rules
- `get_security_standards()` — Security requirements
- `validate_against_standard(artifact, standard)` — Validate code/config
- `get_recent_changes()` — What changed recently
- `subscribe_to_updates(domain)` — Notifications on changes

## Integration

**Each Zilla calls before starting:**
```typescript
// Get domain-specific knowledge
const apiStandards = kbMcp.get_api_standards();
const securityChecklist = kbMcp.get_security_standards();
const designSystem = kbMcp.get_document('/frontend/design-system.md');

// Validate decisions
const isValid = kbMcp.validate_against_standard(myCode, 'backend/code-style');
```

## Updates Flow

```
Zilla discovers new pattern/standard
    ↓
Creates PR to knowledge-base-mcp
    ↓
Documentation review gate
    ↓
Merged to main branch
    ↓
All Zillas notified (via subscription)
    ↓
New standard available for next features
```
