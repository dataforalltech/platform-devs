import { z } from 'zod';

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: z.ZodSchema;
}

const toolSchemas = {
  index_documentation: z.object({
    title: z.string(),
    content: z.string(),
    tags: z.array(z.string()).optional(),
  }),
  search_knowledge_base: z.object({
    query: z.string(),
    limit: z.number().optional(),
  }),
  get_document: z.object({
    doc_id: z.string(),
  }),
  list_documents: z.object({
    tag: z.string().optional(),
  }),
};

export const TOOL_SCHEMAS: Record<string, ToolSchema> = {
  index_documentation: {
    name: 'index_documentation',
    description: 'Index a new document into the knowledge base',
    inputSchema: toolSchemas.index_documentation,
  },
  search_knowledge_base: {
    name: 'search_knowledge_base',
    description: 'Search documents in the knowledge base',
    inputSchema: toolSchemas.search_knowledge_base,
  },
  get_document: {
    name: 'get_document',
    description: 'Retrieve a specific document by ID',
    inputSchema: toolSchemas.get_document,
  },
  list_documents: {
    name: 'list_documents',
    description: 'List all documents, optionally filtered by tag',
    inputSchema: toolSchemas.list_documents,
  },
};

export async function dispatch(
  name: string,
  args: Record<string, unknown>
): Promise<string> {
  switch (name) {
    case 'index_documentation':
      return handleIndexDocumentation(args);
    case 'search_knowledge_base':
      return handleSearchKnowledgeBase(args);
    case 'get_document':
      return handleGetDocument(args);
    case 'list_documents':
      return handleListDocuments(args);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function handleIndexDocumentation(args: Record<string, unknown>): string {
  const { title } = args;
  return JSON.stringify({
    status: 'indexed',
    message: `Document "${title}" indexed successfully`,
  });
}

function handleSearchKnowledgeBase(args: Record<string, unknown>): string {
  const { query } = args;
  return JSON.stringify({
    query,
    results: [],
    total: 0,
  });
}

function handleGetDocument(args: Record<string, unknown>): string {
  const { doc_id } = args;
  return JSON.stringify({
    doc_id,
    status: 'not_found',
  });
}

function handleListDocuments(args: Record<string, unknown>): string {
  const { tag } = args;
  return JSON.stringify({
    tag: tag || 'all',
    documents: [],
    total: 0,
  });
}
