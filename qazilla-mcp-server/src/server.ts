import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema,
  TextResourceContents,
} from '@modelcontextprotocol/sdk/types.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { TOOL_SCHEMAS, dispatch } from './tools/index.js';
import { QAZillaStore } from './db/store.js';
import { getSettings } from './config/settings.js';
import { QAZILLA_SYSTEM_PROMPT } from './prompts/qazillaPrompt.js';
import { getProfilePrompt, getProfileContext, getProfileExamples, Profile } from './prompts/profilePrompts.js';

const settings = getSettings();
const store = new QAZillaStore();

async function handleListTools() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tools: any[] = Object.values(TOOL_SCHEMAS).map((schema) => ({
    name: schema.name,
    description: schema.description,
    inputSchema: {
      type: 'object',
      properties: {},
    },
  }));
  return { tools };
}

async function handleListResources() {
  return {
    resources: [
      {
        uri: 'qazilla_system_prompt',
        name: 'QAZilla System Prompt',
        description: 'System prompt for QAZilla agent specializing in quality assurance, testing and quality engineering',
        mimeType: 'text/plain',
      },
    ],
  };
}

async function handleReadResource(request: {
  params: { uri: string };
}) {
  const { uri } = request.params;

  // PHASE 4: Support profile-based prompts
  if (uri.startsWith('qazilla_system_prompt')) {
    // Extract profile from URI: qazilla_system_prompt?profile=Dev
    const profileMatch = uri.match(/profile=(\w+)/);
    const profile = (profileMatch ? profileMatch[1] : 'Dev') as Profile;

    const profileSpecific = getProfilePrompt(profile);
    const context = getProfileContext(profile);
    const examples = getProfileExamples(profile);

    const fullPrompt = `${QAZILLA_SYSTEM_PROMPT}

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
        } as TextResourceContents,
      ],
    };
  }
  throw new Error(`Unknown resource: ${uri}`);
}

async function handleCallTool(request: {
  params: { name: string; arguments?: Record<string, unknown> };
}) {
  const { name, arguments: args = {} } = request.params;
  const schema = TOOL_SCHEMAS[name];
  if (!schema) {
    throw new Error(`Unknown tool: ${name}`);
  }

  const validated = schema.inputSchema.parse(args);
  const result = await dispatch(name, validated, store);

  return {
    content: [
      {
        type: 'text',
        text: result,
      },
    ],
  };
}

async function main() {
  const transport = new StdioServerTransport();
  const server = new Server(
    {
      name: 'qazilla-mcp-server',
      version: '0.1.0',
    },
    {
      capabilities: {
        tools: {},
        resources: {},
      },
    },
  );

  server.setRequestHandler(ListToolsRequestSchema, handleListTools);
  server.setRequestHandler(ListResourcesRequestSchema, handleListResources);
  server.setRequestHandler(ReadResourceRequestSchema, handleReadResource);
  server.setRequestHandler(CallToolRequestSchema, handleCallTool);

  await server.connect(transport);
}

main().catch(console.error);
