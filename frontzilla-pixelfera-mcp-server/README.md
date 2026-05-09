# FrontZilla-PixelFera MCP Server

A comprehensive MCP (Model Context Protocol) server that serves as a shared capability layer for two specialized AI agents:

- **FrontZilla** — React/Next.js/TypeScript frontend developer
- **PixelFera** — UI/UX/Design System specialist

## Overview

This server exposes **30 tools** organized into 5 categories, enabling structured collaboration between design and frontend development agents. Tools return rich payloads (StructuredPayload pattern) containing not just artifacts but instructions, context, and suggested next steps that agents can consume via LLM.

## Architecture

### Tech Stack
- **Language**: TypeScript 5
- **Runtime**: Node.js 20
- **MCP SDK**: `@modelcontextprotocol/sdk`
- **Validation**: Zod
- **Database**: SQLite (better-sqlite3) with WAL
- **Testing**: Vitest + Playwright
- **Linting**: ESLint + TypeScript

### Database Schema

4 core tables:
- **features** — Track UI features and requirements
- **components** — Store component specs and documentation
- **design_tokens** — Manage design tokens (colors, spacing, typography)
- **workflows** — Orchestrate multi-step workflows

## Tools (30)

### Requirements Analysis (4)
1. `analyze_requirement` — Parse requirements: identify screens, flows, actors, complexity
2. `split_design_and_frontend_tasks` — Divide work between PixelFera and FrontZilla
3. `generate_feature_spec` — Create comprehensive specifications
4. `generate_screen_brief` — Design individual screen briefs

### Design / PixelFera (7)
5. `generate_wireframe` — Create ASCII wireframes with annotations
6. `create_design_tokens` — Define color, typography, spacing, shadows, animations
7. `suggest_ui_components` — Recommend component structure
8. `generate_ux_writing` — Create microcopy (labels, errors, CTAs)
9. `map_visual_states` — Design component states (hover, focus, disabled, etc.)
10. `review_ui_consistency` — Check design system compliance
11. `validate_visual_accessibility` — Verify WCAG 2.1 compliance

### Frontend / FrontZilla (9)
12. `generate_react_component` — Scaffold React components (.tsx)
13. `generate_nextjs_page` — Create Next.js 14+ pages with App Router
14. `generate_typescript_types` — Generate types + Zod schemas
15. `generate_api_service` — Create API clients with CRUD operations
16. `generate_custom_hook` — Build custom React hooks
17. `generate_form_with_validation` — Create forms with React Hook Form + Zod
18. `generate_frontend_tests` — Generate unit + E2E tests
19. `review_frontend_code` — Perform code reviews
20. `suggest_refactor` — Suggest refactoring strategies

### Design System (5)
21. `generate_component_spec` — Create component specifications
22. `generate_component_variants` — Design component variants
23. `document_component` — Generate component documentation
24. `validate_design_system_usage` — Check design token usage
25. `generate_storybook_story` — Create Storybook stories (CSF 3.0)

### Workflow Orchestration (1)
26. `run_ui_feature_workflow` — Orchestrate complete UI feature workflow

## Quick Start

### Setup
```bash
cd frontzilla-pixelfera-mcp-server
npm ci
npm run build
```

### Development
```bash
npm run dev          # Start server with ts-node
npm run build        # Compile TypeScript
npm run lint         # Check code style
npm run type-check   # Run type checker
npm test            # Run tests
```

### Usage
```bash
# Build and run
npm run build
node dist/server.js

# Or run directly with Node ESM loader
node --loader ts-node/esm src/server.ts
```

## System Prompts

The server exposes 3 system prompts as MCP resources:

1. **frontzilla_system_prompt** — Identity, expertise, responsibilities, tools, best practices for FrontZilla
2. **pixelfera_system_prompt** — Identity, expertise, responsibilities, tools, design principles for PixelFera
3. **orchestrator_prompt** — Coordination strategy, workflow management, collaboration points

Access via:
```
GET /resource/prompt://frontzilla_system_prompt
GET /resource/prompt://pixelfera_system_prompt
GET /resource/prompt://orchestrator_prompt
```

## StructuredPayload Pattern

All tools return a rich StructuredPayload:

```typescript
{
  tool: string;
  agent: "frontzilla" | "pixelfera" | "shared" | "orchestrator";
  timestamp: string;
  payload: T;                          // The artifact
  instructions: string;                 // What to do with it
  context_for_llm: string;             // Context for agent LLM
  metadata: {
    feature_id?: string;
    component_id?: string;
    related_tools?: string[];          // Next steps
  };
}
```

## Workflow Example

### User Request: "Build a login form"

1. **Analyze** (`analyze_requirement`)
   - Identify screens: [Login page, Reset password]
   - Identify flows: [Email login, OAuth]
   - Complexity: medium

2. **Split Tasks** (`split_design_and_frontend_tasks`)
   - PixelFera: wireframes, design tokens, component specs
   - FrontZilla: React components, Next.js pages, forms, tests

3. **Design Phase** (PixelFera)
   - `generate_wireframe` — Create login page layout
   - `create_design_tokens` — Define form styling
   - `generate_ux_writing` — Write form labels, error messages
   - `map_visual_states` — Design input states

4. **Frontend Phase** (FrontZilla)
   - `generate_react_component` — Create form components
   - `generate_form_with_validation` — Implement validation
   - `generate_api_service` — Create authentication service
   - `generate_frontend_tests` — Write tests

5. **Integration** (Orchestrator)
   - Coordinate handoffs
   - Verify design system compliance
   - Ensure tests pass

## Testing

```bash
# Run all tests
npm test

# Run tests with UI
npm run test:ui

# Run specific test file
npm test store.test.ts
```

Test coverage:
- ✓ Store operations (create, read, update features/components/tokens/workflows)
- ✓ Tool dispatch and error handling
- ✓ Workflow orchestration and agent coordination
- ✓ Integration workflows (design → frontend)

## CI/CD

### GitHub Actions
- **test-typescript**: Lint, type-check, test, build
- **test** (Python servers): Unit tests, linting, coverage
- **security**: Bandit scan for Python code

### Port Configuration
- Port: **7097** (reserved for this server)
- See AGENTS.md §47 for port allocation

## Project Structure

```
frontzilla-pixelfera-mcp-server/
├── src/
│   ├── server.ts                    # MCP server entry point
│   ├── config/settings.ts           # Environment configuration
│   ├── db/store.ts                  # SQLite store (4 tables)
│   ├── schemas/                     # Zod schemas (requirement, design, frontend, workflow)
│   ├── tools/
│   │   ├── index.ts                 # Tool registry + dispatch
│   │   ├── requirements/            # 4 requirement tools
│   │   ├── design/                  # 7 design tools
│   │   ├── frontend/                # 9 frontend tools
│   │   ├── design-system/           # 5 design system tools
│   │   └── workflows/               # 1 orchestration tool
│   ├── prompts/index.ts             # System prompts for agents
│   └── utils/
│       ├── responseFormatter.ts     # StructuredPayload builder
│       └── validators.ts            # Shared validation (Zod)
├── tests/
│   ├── store.test.ts               # Database tests
│   ├── tools.test.ts               # Tool dispatch tests
│   └── workflows.test.ts           # Workflow orchestration tests
├── package.json
├── tsconfig.json
├── .eslintrc.json
├── vitest.config.ts
└── .mcp.json
```

## Integration with Platform

### Consumed by
- **FrontZilla Agent** (MCP client) — Uses tools to scaffold frontend code
- **PixelFera Agent** (MCP client) — Uses tools to design UI components
- **Orchestrator** — Coordinates both agents

### Consumes
- **docs-mcp** — For documentation generation and templates
- **qa-mcp** — For test utilities and quality checks
- **deploy-mcp** — For code generation and deployment references

### Registration
```bash
# Via services-mcp:
mcp__services-mcp__register_service(
  name="frontzilla-pixelfera-mcp",
  port=7097,
  type="mcp",
  environment="dev"
)
```

## Best Practices

### For FrontZilla
- Always use TypeScript for type safety
- Follow React patterns: memoization, lazy loading, code splitting
- Keep components pure and testable
- Respect design tokens from PixelFera
- Write comprehensive tests (>80% coverage)
- Implement WCAG accessibility standards

### For PixelFera
- Start with user research and requirements
- Use consistent design patterns and tokens
- Document all components and variants
- Consider accessibility from the start
- Keep design system lean and focused
- Communicate changes clearly to development team

### For Orchestrator
- Clearly divide responsibilities
- Manage design-to-code handoffs
- Flag blockers immediately
- Iterate based on feedback
- Ensure quality and consistency

## Future Enhancements

- [ ] Prompt caching for system prompts
- [ ] Real-time collaboration features
- [ ] Design to code sync (bidirectional)
- [ ] Component library export (npm, Figma)
- [ ] Performance monitoring and analytics
- [ ] A/B testing framework integration
- [ ] Multi-language support (i18n)
- [ ] Dark mode system-wide support

## License

Proprietary — DataForAll Platform

## Contact

Platform Team — caiog@dataforall.tech
