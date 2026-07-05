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
import { QAEngineerStore } from './db/store.js';
import { getSettings } from './config/settings.js';
import { QA_ENGINEER_SYSTEM_PROMPT } from './prompts/qa-engineerPrompt.js';

const settings = getSettings();
const store = new QAEngineerStore();

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
        uri: 'qa-engineer_system_prompt',
        name: 'QA-Engineer System Prompt',
        description: 'System prompt for QA-Engineer agent specializing in quality assurance, testing and quality engineering',
        mimeType: 'text/plain',
      },
    ],
  };
}

async function handleReadResource(request: {
  params: { uri: string };
}) {
  const { uri } = request.params;
  if (uri === 'qa-engineer_system_prompt') {
    return {
      contents: [
        {
          uri: 'qa-engineer_system_prompt',
          mimeType: 'text/plain',
          text: QA_ENGINEER_SYSTEM_PROMPT,
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
      name: 'qa-engineer-mcp-server',
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
