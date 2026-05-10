# ProductZilla MCP Server

**Product Manager specialist agent** for transforming problems, user needs, and market opportunities into clear, prioritized, measurable, and execution-ready products and features.

## Overview

ProductZilla is an MCP (Model Context Protocol) server that provides 18 tools for product management across discovery, delivery, and metrics. It helps teams:

- Analyze product problems and market opportunities
- Define product vision, mission, and strategy
- Create user personas and journey maps
- Write feature specs and user stories
- Define MVP scope and phased releases
- Prioritize backlogs using RICE, MoSCoW, ICE
- Calculate impact scores
- Define success metrics and KPIs
- Plan go-to-market strategy
- Prepare handoffs for Design, Architecture, and Engineering

## Installation

```bash
cd productzilla-mcp-server
npm install
npm run build
```

## Usage

### As MCP Server

The server is registered in `/home/dev/.claude.json`:

```json
{
  "productzilla-mcp-server": {
    "command": "bash",
    "args": ["-c", "cd /home/dev/repos/platform-devs/productzilla-mcp-server && node dist/server.js"]
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

### Analysis & Strategy
- `analyze_product_problem` — Identify root cause, user pain, market opportunity
- `define_product_vision` — Define vision, mission, goals, success criteria
- `map_user_personas` — Create detailed user personas with goals and pain points
- `map_user_journey` — Map journey stages, touchpoints, emotions, opportunities

### Definition & Specifications
- `generate_feature_spec` — Write feature specification with scope and metrics
- `generate_user_stories` — Generate user stories in "As a/I want/so that" format
- `generate_acceptance_criteria` — Define testable acceptance criteria (Given/When/Then)
- `define_mvp_scope` — Define MVP, Beta, and v2 phased scope

### Prioritization & Scoring
- `prioritize_backlog` — Prioritize using RICE, MoSCoW, ICE frameworks
- `calculate_rice_score` — Calculate Reach × Impact × Confidence / Effort

### Metrics & Goals
- `define_product_metrics` — Define KPIs, leading/lagging indicators, tracking method
- `generate_release_plan` — Create phased release timeline and GTM plan
- `generate_discovery_questions` — Generate research questions for validation

### Risk & Execution
- `map_product_risks` — Identify value, usability, viability, feasibility risks
- `generate_go_to_market_brief` — Create GTM strategy, messaging, channels
- `generate_handoff_to_design` — Brief for Design team with journeys and requirements
- `generate_handoff_to_architecture` — Brief for Architecture with tech requirements
- `generate_handoff_to_engineering` — Brief for Engineering with user stories and timeline

## Database

ProductZilla uses SQLite (WAL mode) with 4 tables:

- **features**: Store feature specs and problem statements
- **user_stories**: Track user stories and acceptance criteria
- **backlogs**: Manage prioritized backlog items
- **releases**: Plan phased releases and timelines

## Testing

```bash
npm test
# Run smoke tests: verifies 18 tools present and system prompt defined
```

## Configuration

Environment variables (defaults shown):

```
PRODUCTZILLA_DB_PATH=/tmp/productzilla.db
PRODUCTZILLA_LOG_LEVEL=info
NODE_ENV=development
```

## System Prompt

ProductZilla's system prompt emphasizes:

- **Strategic thinking**: Vision, goals, roadmap planning
- **User-centric approach**: Personas, journey maps, discovery
- **Analytical**: RICE scoring, risk mapping, metrics
- **Pragmatic**: MVP scope, phased releases, GTM
- **Communication**: Clear handoffs to Design, Architecture, Engineering

The prompt is exposed as MCP resource: `productzilla_system_prompt`

## Integration

ProductZilla works with:

- **PixelFera**: Design team for UX/UI specifications
- **ArchZilla**: Architecture team for technical requirements
- **FrontZilla**: Frontend team for component specifications
- **BackZilla**: Backend team for API and data specifications
- **OpsZilla**: DevOps team for deployment planning

## Architecture

```
productzilla-mcp-server/
├── src/
│   ├── server.ts           ← MCP protocol implementation
│   ├── tools/index.ts      ← 18 tools + dispatch logic
│   ├── prompts/
│   │   └── productzillaPrompt.ts
│   ├── db/store.ts         ← SQLite persistence
│   └── config/settings.ts  ← Environment config
└── tests/
    └── smoke.test.ts
```

## Version

0.1.0 — Product management tools with 18 specialized functions

---

For integration with Claude Code, reference the system prompt `productzilla_system_prompt` for detailed guidance on product-driven decision-making.
