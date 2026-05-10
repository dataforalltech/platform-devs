import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateFormWithValidationSchema } from '../../schemas/frontend.schema.js';

export async function generateFormWithValidation(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateFormWithValidationSchema.parse(args);
  const library = input.library || 'react-hook-form';

  const typescriptCode = `import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const validationSchema = z.object({
  ${input.fields.map((f) => `${f.name}: z.string()${f.required ? '' : '.optional()'}`).join(',\n  ')}
});

type FormData = z.infer<typeof validationSchema>;

export function ${input.form_name}() {
  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(validationSchema),
  });

  const onSubmit = async (data: FormData) => {
    console.log(data);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      ${input.fields.map((f) => `<input {...register('${f.name}')} placeholder="${f.label}" />`).join('\n      ')}
      <button type="submit">Submit</button>
    </form>
  );
}
`;

  const payload = {
    filename: `${input.form_name}.tsx`,
    typescript_code: typescriptCode,
    form_name: input.form_name,
    validation_schema: 'validationSchema',
  };

  return createStructuredPayload({
    tool: 'generate_form_with_validation',
    agent: 'frontzilla',
    payload,
    instructions: 'Customize form fields and validation. Add error handling and success messages.',
    context_for_llm: `Form: ${input.form_name}. Library: ${library}. Fields: ${input.fields.map((f) => f.name).join(', ')}.`,
    related_tools: ['generate_typescript_types', 'generate_frontend_tests'],
  });
}
