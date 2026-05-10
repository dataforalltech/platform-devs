# ArchZilla MCP Server

**Software Architecture specialist agent** for designing and evaluating robust, scalable, secure, observable, and sustainable software architectures.

## Overview

ArchZilla is an MCP (Model Context Protocol) server that provides 18 tools for architectural analysis, design, and decision-making. It helps teams:

- Analyze architectural requirements and recommend styles
- Design solution blueprints with clear layer separation
- Define system modules and domain-driven design contexts
- Generate architecture diagrams (C4, sequence)
- Establish API and event contracts
- Design data, security, and observability architectures
- Document decisions with ADRs
- Review architectures against quality criteria
- Map and mitigate architectural risks
- Create technical roadmaps
- Define integration strategies
- Evaluate architecture trade-offs

## Installation

```bash
cd archzilla-mcp-server
npm install
npm run build
```

## Usage

### As MCP Server

The server is registered in `/home/dev/.claude.json`:

```json
{
  "archzilla-mcp-server": {
    "command": "bash",
    "args": ["-c", "cd /home/dev/repos/platform-devs/archzilla-mcp-server && node dist/server.js"]
  }
}
```

### Running Directly

```bash
npm start
# or
node dist/server.js
```

## Tools (18)

### Requirement Analysis
- `analyze_architecture_requirement` — Analyze requirements and recommend architectural styles
- `generate_feature_spec` — Generate detailed architectural specifications
- `define_non_functional_requirements` — Define performance, availability, security, cost requirements

### Solution Design
- `generate_solution_blueprint` — Create comprehensive architecture blueprint
- `define_system_modules` — Define system modules, boundaries, and dependencies
- `define_bounded_contexts` — Apply DDD principles to define bounded contexts

### Visualization
- `generate_c4_diagram` — Generate C4 architecture diagrams (context, container, component, code)
- `generate_sequence_diagram` — Generate sequence diagrams for key flows

### Contracts & Standards
- `generate_api_guidelines` — Define API design standards (REST, GraphQL, gRPC)
- `generate_event_contracts` — Define event-driven architecture contracts
- `generate_adr` — Generate Architecture Decision Records

### Cross-Cutting Concerns
- `generate_data_architecture` — Design databases, warehouses, pipelines
- `generate_security_architecture` — Design IAM, encryption, Zero Trust, compliance
- `generate_observability_architecture` — Design logging, metrics, tracing, alerting

### Evaluation & Governance
- `review_architecture` — Review architecture against quality criteria
- `map_architecture_risks` — Identify and map architectural risks
- `evaluate_architecture_tradeoffs` — Evaluate options and trade-offs
- `define_integration_strategy` — Design integration patterns and error handling
- `generate_technical_roadmap` — Create phased evolution plan

## Database

ArchZilla uses SQLite (WAL mode) with 4 tables:

- **architectures**: Store design blueprints and specifications
- **decisions**: Track ADRs and decision rationale
- **diagrams**: Cache generated C4 and sequence diagrams
- **reviews**: Store architecture review findings and scores

## Testing

```bash
npm test
# Run smoke tests: verifies 18 tools present and system prompt defined
```

## Configuration

Environment variables (defaults shown):

```
ARCHZILLA_DB_PATH=/tmp/archzilla.db
ARCHZILLA_LOG_LEVEL=info
NODE_ENV=development
```

## System Prompt

ArchZilla's system prompt emphasizes:

- **Strategic thinking**: Long-term evolution and scalability
- **Analytical approach**: Trade-off evaluation, complexity assessment
- **Technical expertise**: Patterns, integrations, data architecture
- **Sustainability**: Maintainability, observability, cost efficiency
- **Governance**: Documentation, ADRs, architecture standards

The prompt is exposed as MCP resource: `archzilla_system_prompt`

## Integration

ArchZilla integrates with:

- **docs-mcp**: ADR documentation and templates
- **qa-mcp**: Architecture review and quality metrics
- **deploy-mcp**: Technical roadmap and deployment automation

## Architecture

```
archzilla-mcp-server/
├── src/
│   ├── server.ts           ← MCP protocol implementation
│   ├── tools/index.ts      ← 18 tools + dispatch logic
│   ├── prompts/
│   │   └── archzillaPrompt.ts
│   ├── db/store.ts         ← SQLite persistence
│   └── config/settings.ts  ← Environment config
└── tests/
    └── smoke.test.ts
```

## Version

0.1.0 — Architecture analysis and design tools with 18 specialized functions

---

For integration with Claude Code, reference the system prompt `archzilla_system_prompt` for detailed guidance on architecture-driven decision-making.
