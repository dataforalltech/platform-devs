import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { ListToolsRequestSchema, CallToolRequestSchema, ListResourcesRequestSchema, ReadResourceRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { getSettings } from './config/settings.js';
import { FrontzillaPixelferaStore } from './db/store.js';
import { getToolSchemas, dispatchTool } from './tools/index.js';
import { getFrontzillaPrompt, getPixelferaPrompt, getOrchestratorPrompt } from './prompts/index.js';
import { getProfilePrompt, getProfileContext, getProfileExamples, Profile } from './prompts/profilePrompts.js';

const settings = getSettings();
const store = new FrontzillaPixelferaStore(settings.dbPath);

const server = new Server(
  {
    name: 'frontzilla-pixelfera-mcp-server',
    version: '0.1.0',
  },
  {
    capabilities: {
      tools: {},
      resources: {},
      prompts: {},
    },
  }
);

// List tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: getToolSchemas(),
  };
});

// Call tool
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    const result = await dispatchTool(request.params.name, request.params.arguments || {}, store, settings);
    return {
      content: [
        {
          type: 'text' as const,
          text: JSON.stringify(result, null, 2),
        },
      ],
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    return {
      content: [
        {
          type: 'text' as const,
          text: JSON.stringify(
            {
              error: 'tool_execution_failed',
              tool: request.params.name,
              message: errorMessage,
            },
            null,
            2
          ),
        },
      ],
      isError: true,
    };
  }
});

// List resources (prompts)
server.setRequestHandler(ListResourcesRequestSchema, async () => {
  return {
    resources: [
      {
        uri: 'prompt://frontzilla_system_prompt',
        name: 'FrontZilla System Prompt',
        description: 'System prompt for FrontZilla agent (React/Next.js frontend developer)',
        mimeType: 'text/plain',
      },
      {
        uri: 'prompt://pixelfera_system_prompt',
        name: 'PixelFera System Prompt',
        description: 'System prompt for PixelFera agent (UI/UX/Design System specialist)',
        mimeType: 'text/plain',
      },
      {
        uri: 'prompt://orchestrator_prompt',
        name: 'Orchestrator Prompt',
        description: 'Prompt for orchestrating collaboration between FrontZilla and PixelFera',
        mimeType: 'text/plain',
      },
    ],
  };
});

// Read resource
server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
  const uri = request.params.uri;

  // PHASE 4: Support profile-based prompts
  if (uri.startsWith('prompt://frontzilla_system_prompt')) {
    const profileMatch = uri.match(/profile=(\w+)/);
    const profile = (profileMatch ? profileMatch[1] : 'Dev') as Profile;

    const basePrompt = getFrontzillaPrompt();
    const profileSpecific = getProfilePrompt(profile);
    const context = getProfileContext(profile);
    const examples = getProfileExamples(profile);

    const fullPrompt = `${basePrompt}

---

## PHASE 4: Profile-Based Customization

### Current Profile: ${profile}
### Context: ${context}

${profileSpecific}

${examples}

---

Apply the above guidance based on the ${profile} profile when responding to user requests.`;

    return {
      contents: [
        {
          uri,
          mimeType: 'text/plain',
          text: fullPrompt,
        },
      ],
    };
  } else if (uri === 'prompt://pixelfera_system_prompt') {
    return {
      contents: [
        {
          uri,
          mimeType: 'text/plain',
          text: getPixelferaPrompt(),
        },
      ],
    };
  } else if (uri === 'prompt://orchestrator_prompt') {
    return {
      contents: [
        {
          uri,
          mimeType: 'text/plain',
          text: getOrchestratorPrompt(),
        },
      ],
    };
  } else {
    return {
      contents: [
        {
          uri,
          mimeType: 'text/plain',
          text: 'Resource not found',
        },
      ],
    };
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('FrontZilla-PixelFera MCP Server running on stdio');
}

main().catch((error) => {
  console.error('Server error:', error);
  process.exit(1);
});
