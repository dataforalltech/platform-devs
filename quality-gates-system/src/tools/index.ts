import { z } from 'zod';

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: z.ZodSchema;
}

const toolSchemas = {
  register_gate: z.object({
    gate_id: z.string(),
    gate_type: z.string(),
    description: z.string().optional(),
  }),
  evaluate_gate: z.object({
    gate_id: z.string(),
    context: z.record(z.unknown()).optional(),
  }),
  get_gate_status: z.object({
    gate_id: z.string(),
  }),
  list_gates: z.object({
    gate_type: z.string().optional(),
  }),
};

export const TOOL_SCHEMAS: Record<string, ToolSchema> = {
  register_gate: {
    name: 'register_gate',
    description: 'Register a new quality gate',
    inputSchema: toolSchemas.register_gate,
  },
  evaluate_gate: {
    name: 'evaluate_gate',
    description: 'Evaluate a quality gate',
    inputSchema: toolSchemas.evaluate_gate,
  },
  get_gate_status: {
    name: 'get_gate_status',
    description: 'Get the status of a quality gate',
    inputSchema: toolSchemas.get_gate_status,
  },
  list_gates: {
    name: 'list_gates',
    description: 'List all quality gates, optionally filtered by type',
    inputSchema: toolSchemas.list_gates,
  },
};

export async function dispatch(
  name: string,
  args: Record<string, unknown>
): Promise<string> {
  switch (name) {
    case 'register_gate':
      return handleRegisterGate(args);
    case 'evaluate_gate':
      return handleEvaluateGate(args);
    case 'get_gate_status':
      return handleGetGateStatus(args);
    case 'list_gates':
      return handleListGates(args);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function handleRegisterGate(args: Record<string, unknown>): string {
  const { gate_id } = args;
  return JSON.stringify({
    gate_id,
    status: 'registered',
  });
}

function handleEvaluateGate(args: Record<string, unknown>): string {
  const { gate_id } = args;
  return JSON.stringify({
    gate_id,
    passed: true,
    score: 100,
  });
}

function handleGetGateStatus(args: Record<string, unknown>): string {
  const { gate_id } = args;
  return JSON.stringify({
    gate_id,
    status: 'passing',
    last_eval: new Date().toISOString(),
  });
}

function handleListGates(args: Record<string, unknown>): string {
  const { gate_type } = args;
  return JSON.stringify({
    gate_type: gate_type || 'all',
    gates: [],
    total: 0,
  });
}
