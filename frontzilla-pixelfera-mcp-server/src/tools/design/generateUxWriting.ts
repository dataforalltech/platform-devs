import { createStructuredPayload } from '../../utils/responseFormatter.js';
import { FrontzillaPixelferaStore } from '../../db/store.js';
import { GenerateUxWritingSchema } from '../../schemas/design.schema.js';

export async function generateUxWriting(
  args: Record<string, unknown>,
  store: FrontzillaPixelferaStore
): Promise<Record<string, unknown>> {
  const input = GenerateUxWritingSchema.parse(args);
  const tone = input.tone || 'professional';

  const writing = {
    labels: {
      firstName: 'First Name',
      lastName: 'Last Name',
      email: 'Email Address',
      password: 'Password',
    },
    error_messages: {
      required: tone === 'friendly' ? 'Oops! This is required.' : 'This field is required.',
      invalid_email: 'Please enter a valid email address.',
      password_weak: 'Password must be at least 8 characters.',
    },
    cta_copy: [
      { action: 'submit', text: tone === 'casual' ? 'Let\'s go!' : 'Submit' },
      { action: 'cancel', text: 'Cancel' },
      { action: 'delete', text: 'Delete Forever' },
    ],
    empty_states: {
      no_results: 'No results found. Try a different search.',
      no_items: 'No items yet. Create your first one!',
      loading: 'Loading your data...',
    },
  };

  return createStructuredPayload({
    tool: 'generate_ux_writing',
    agent: 'pixelfera',
    payload: { writing, tone },
    instructions: 'Review and refine UX copy. Ensure tone consistency. Share with FrontZilla.',
    context_for_llm: `UX writing for: ${input.context}. Tone: ${tone}. Includes labels, errors, CTAs, empty states.`,
    related_tools: ['generate_screen_brief', 'generate_form_with_validation'],
  });
}
