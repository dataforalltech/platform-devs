import { z } from 'zod';

export interface ToolSchema {
  name: string;
  description: string;
  inputSchema: z.ZodSchema;
}

const toolSchemas = {
  validate_handoff: z.object({
    from_zilla: z.string(),
    to_zilla: z.string(),
    handoff_data: z.record(z.unknown()),
  }),
  check_governance: z.object({
    zilla_name: z.string(),
    check_type: z.string().optional(),
  }),
  validate_output: z.object({
    zilla_name: z.string(),
    output: z.record(z.unknown()),
  }),
  get_validation_rules: z.object({
    from_zilla: z.string(),
    to_zilla: z.string(),
  }),
};

export const TOOL_SCHEMAS: Record<string, ToolSchema> = {
  validate_handoff: {
    name: 'validate_handoff',
    description: 'Validate a handoff between two Zillas',
    inputSchema: toolSchemas.validate_handoff,
  },
  check_governance: {
    name: 'check_governance',
    description: 'Check governance compliance for a Zilla',
    inputSchema: toolSchemas.check_governance,
  },
  validate_output: {
    name: 'validate_output',
    description: 'Validate output from a Zilla against expected schema',
    inputSchema: toolSchemas.validate_output,
  },
  get_validation_rules: {
    name: 'get_validation_rules',
    description: 'Get validation rules for a handoff between two Zillas',
    inputSchema: toolSchemas.get_validation_rules,
  },
};

export async function dispatch(
  name: string,
  args: Record<string, unknown>
): Promise<string> {
  switch (name) {
    case 'validate_handoff':
      return handleValidateHandoff(args);
    case 'check_governance':
      return handleCheckGovernance(args);
    case 'validate_output':
      return handleValidateOutput(args);
    case 'get_validation_rules':
      return handleGetValidationRules(args);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function handleValidateHandoff(args: Record<string, unknown>): string {
  const { from_zilla, to_zilla } = args;
  return JSON.stringify({
    from: from_zilla,
    to: to_zilla,
    valid: true,
    errors: [],
  });
}

function handleCheckGovernance(args: Record<string, unknown>): string {
  const { zilla_name } = args;
  return JSON.stringify({
    zilla: zilla_name,
    compliant: true,
    violations: [],
  });
}

function handleValidateOutput(args: Record<string, unknown>): string {
  const { zilla_name } = args;
  return JSON.stringify({
    zilla: zilla_name,
    valid: true,
    errors: [],
  });
}

function handleGetValidationRules(args: Record<string, unknown>): string {
  const { from_zilla, to_zilla } = args;
  return JSON.stringify({
    from: from_zilla,
    to: to_zilla,
    rules: [],
  });
}
