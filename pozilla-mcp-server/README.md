# POZilla MCP Server

**POZilla** — Product Owner specialist agent for backlog management, refinement, and agile delivery.

## Overview

POZilla transforms business demands, product vision, and functional requirements into clear, prioritized, testable, and deployment-ready backlogs.

## Capabilities

POZilla specializes in:
- **Backlog Management** — Create, organize, break down, and refine
- **User Stories** — Clear, testable user stories with acceptance criteria
- **Acceptance Criteria** — Define testable conditions in Given/When/Then format
- **Prioritization** — MoSCoW, value vs. effort frameworks
- **Dependencies** — Map blockers and integrations
- **Delivery** — Track execution and validate deliverables
- **Communication** — Translate business requirements into technical specifications

## Tools (17)

### Demand & Analysis
- `analyze_business_demand` — Analyze objective, scope, impact, constraints
- `generate_epic` — Generate epic with title, description, success criteria

### Feature Breakdown
- `generate_feature_breakdown` — Break epic into features with effort estimates
- `generate_user_stories` — Generate user stories from feature description
- `generate_acceptance_criteria` — Define clear, testable acceptance criteria
- `generate_gherkin_scenarios` — Generate BDD scenarios in Given/When/Then format

### Agile Process
- `define_definition_of_ready` — Create DoR checklist for clarity and readiness
- `define_definition_of_done` — Create DoD checklist for deployment readiness
- `prioritize_backlog_items` — Prioritize using MoSCoW, value, dependencies, risk
- `map_dependencies` — Map internal, external, blocking dependencies
- `identify_scope_risks` — Identify ambiguity, dependency, feasibility risks

### Sprint Planning
- `prepare_sprint_backlog` — Select stories, estimate, and plan sprint

### Delivery & Documentation
- `generate_release_notes` — Generate user-facing release notes
- `generate_homologation_checklist` — Create QA/testing checklist
- `generate_jira_tasks` — Generate Jira task format with fields and labels
- `refine_feature` — Break into stories, identify unknowns, validate readiness
- `validate_story_readiness` — Validate story clarity, scope, and blockers

## Database Schema

SQLite with WAL mode for thread-safe operations:

```sql
epics      — Epic definitions and status
features   — Features broken from epics
stories    — User stories with criteria
tasks      — Implementation tasks
```

## Installation

```bash
npm install
npm run build
```

## Configuration

Environment variables:
- `POZILLA_DB_PATH` — SQLite database path (default: `/tmp/pozilla.db`)
- `POZILLA_LOG_LEVEL` — Log level: debug|info|warn|error (default: `info`)
- `NODE_ENV` — Environment: development|production (default: `development`)

## Testing

```bash
npm test
```

Runs 4 smoke tests:
- Tool count verification (17 tools)
- Tool name validation
- System prompt verification
- Schema properties validation

## Usage

POZilla is consumed via MCP protocol as a language model tool provider. Agents call tools via:

```
await callTool('analyze_business_demand', {
  demand_description: "...",
  business_goal: "...",
  affected_users: ["..."],
  constraints: ["..."]
})
```

Each tool returns a structured JSON response with actionable backlog items.

## Port

- **Development**: 7102 (stdio transport via MCP SDK)
- **Registration**: `/home/dev/.claude.json`

## Architecture

```
src/
├── server.ts              — MCP protocol handlers
├── tools/index.ts         — 17 tools + dispatch
├── db/store.ts           — SQLite operations
├── config/settings.ts    — Environment config
└── prompts/
    └── pozillaPrompt.ts  — System prompt resource
```

## MCP Features

- **Tools**: 17 specialized backlog & delivery tools
- **Resources**: System prompt (`pozilla_system_prompt`)
- **Capabilities**: Tools, resources
- **Transport**: Stdio (MCP SDK)

---

**POZilla: transforma ideia solta em backlog pronto para sprint.**
