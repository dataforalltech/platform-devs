# dai-mcp — DAI Orchestrator as MCP

MCP Server that exposes DAI (Data for All — Agentic Intelligence) as a callable agent interface. Allows other agents to invoke DAI orchestrator, workflows, and knowledge bases.

## Features

- **Multi-turn Chat** — Conversational interface with DAI
- **Data Analysis** — Ask DAI to analyze data for specific objectives
- **Workflow Generation** — Generate and execute workflows
- **Session Management** — Access session history and memory
- **Knowledge Base** — Query business and technical knowledge bases

## Tools

### dai_chat
Send message to DAI orchestrator and get response.
- Inputs: `message`, optional `context` (dict with additional context)
- Returns: DAI response with reasoning and actions taken

### dai_analyze
Ask DAI to analyze data for specific objective.
- Inputs: `objective`, `data` (dict with data to analyze)
- Returns: analysis results with insights and recommendations

### dai_generate_workflow
Ask DAI to generate workflow for specific objective.
- Inputs: `objective`, optional `constraints` (execution constraints)
- Returns: generated workflow definition with steps and logic

### dai_execute_workflow
Execute workflow via DAI orchestrator.
- Inputs: `workflow_id`, optional `inputs` (workflow input parameters)
- Returns: workflow execution results and status

### dai_get_session_history
Get session history and memory from DAI.
- Inputs: `session_id`
- Returns: conversation history, decisions, and learned context

### dai_get_knowledge_base
Query DAI knowledge base (business or technical).
- Inputs: `query`, optional `kb_type` (business|technical, default: business)
- Returns: relevant knowledge entries with relevance scores

## Installation

```bash
pip install -e .
```

## Configuration

Environment variables (prefix: `MCP_DAI_`):

- `MCP_DAI_BASE_URL` — DAI orchestrator API endpoint (default: `http://localhost:5003/api/v1`)
- `MCP_DAI_API_KEY` — Authentication token
- `MCP_DAI_TIMEOUT_SECONDS` — HTTP timeout for long-running workflows (default: 180)

## Running

```bash
python -m src.server.mcp_server
```

## Error Handling

All tools return JSON responses:

**Success:**
```json
{"status": "ok", "data": {...}}
```

**Error:**
```json
{"error": "ErrorType", "details": "error message"}
```

Error types: `NotFound`, `BadRequest`, `HTTPError`, `Exception`

## Cross-Agent Communication

This MCP enables other agents to:
1. **Ask DAI to analyze** company data through `dai_analyze`
2. **Request workflows** from DAI's registry via `dai_generate_workflow`
3. **Execute complex operations** by calling `dai_execute_workflow`
4. **Access institutional knowledge** from `dai_get_knowledge_base`
5. **Track decisions** made by DAI via `dai_get_session_history`

Example use case: A custom agent analyzing competitor data can invoke `dai_chat` to ask DAI for strategic insights, leveraging DAI's full context and multi-agent capabilities.

## Related

- DAI Orchestrator (`platform-dai`)
- Multi-tenant Team of Agents (LangGraph)
- Phase 4 MCP Architecture (Fase 4 da Roadmap)
