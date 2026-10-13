/**
 * Context-aware suggested questions.
 *
 * Which prompts to offer depends on where the user is — and, on the Predict
 * screen, on whether a verdict has just come back, since "explain this result"
 * is only meaningful once there is one.
 *
 * Every entry is plain text submitted through exactly the same path a typed
 * message takes (`onSuggestion` -> `send`). None of them maps to a canned or
 * pre-written reply, and none of them is an answer the frontend already holds:
 * the assistant answers from its own tool calls, so a suggestion is a question,
 * never a shortcut to a fake response.
 *
 * Several are recognised by the backend's deterministic routers — "explain my
 * latest prediction", "show my history" — which makes them work even when the
 * model hesitates. The rest are answered by the model normally.
 *
 * Kept in their own module so `ChatSuggestions.jsx` exports only a component,
 * which is what keeps React Fast Refresh working during development.
 */

import { AI_CONTEXT } from '@/context/aquaAIContextObject'

/** Icons reused across sets, so the same idea looks the same everywhere. */
const ICONS = {
  sparkle: 'M12 3v4m0 10v4M3 12h4m10 0h4M6.3 6.3l2.8 2.8m5.8 5.8l2.8 2.8m0-11.4l-2.8 2.8m-5.8 5.8l-2.8 2.8',
  pulse: 'M3 12h4l2-6 4 12 2-6h6',
  chart: 'M4 20V10m5 10V4m5 16v-7m5 7V8',
  droplet: 'M12 3c4 5 6 8 6 11a6 6 0 0 1-12 0c0-3 2-6 6-11Z',
  bell: 'M15 17h5l-1.4-2.1A2 2 0 0 1 18 13.8V11a6 6 0 1 0-12 0v2.8a2 2 0 0 1-.4 1.2L4 17h5m6 0a3 3 0 0 1-6 0',
  clock: 'M12 8v4l3 2M3.05 11a9 9 0 1 1 .5 3M3 4v4h4',
  brain: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-8 9a8 8 0 0 1 16 0',
  shield: 'M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6l7-3Z',
}

/**
 * One list per screen. Order matters: the first suggestion is the most likely
 * intent on that screen, so the row reads as a set of shortcuts rather than a
 * random sample.
 */
export const SUGGESTIONS_BY_CONTEXT = {
  // --- Dashboard: orientation, then the user's own numbers ---
  [AI_CONTEXT.dashboard]: [
    { label: 'What is my latest prediction?', icon: ICONS.clock },
    { label: 'Explain my dashboard.', icon: ICONS.chart },
    { label: 'Show my recent alerts.', icon: ICONS.bell },
  ],

  // --- Predict, before submitting: the form and the model behind it ---
  [AI_CONTEXT.prediction]: [
    { label: 'What is pH?', icon: ICONS.droplet },
    { label: 'How does the prediction work?', icon: ICONS.brain },
    { label: 'What does confidence mean?', icon: ICONS.pulse },
  ],

  // --- Predict, once a verdict is on screen ---
  [AI_CONTEXT.predictionResult]: [
    { label: 'Explain this result.', icon: ICONS.brain },
    { label: 'What does this prediction mean?', icon: ICONS.sparkle },
    { label: 'Show my history.', icon: ICONS.clock },
  ],

  // --- History: the record list and its aggregates ---
  [AI_CONTEXT.history]: [
    { label: 'Explain my latest prediction.', icon: ICONS.brain },
    { label: 'How many unsafe predictions do I have?', icon: ICONS.shield },
  ],

  // --- Alerts: the notification list ---
  [AI_CONTEXT.alerts]: [
    { label: 'Explain this alert.', icon: ICONS.bell },
    { label: 'What is my latest prediction?', icon: ICONS.clock },
  ],

  // --- Anything else (profile, an unknown path): a general starting set ---
  [AI_CONTEXT.general]: [
    { label: 'What is my latest prediction?', icon: ICONS.clock },
    { label: 'Why did my sample come back unsafe?', icon: ICONS.shield },
    { label: 'What can you do?', icon: ICONS.sparkle },
  ],
}

// Profile has no bespoke prompts — the general set is the right answer there.
SUGGESTIONS_BY_CONTEXT[AI_CONTEXT.profile] = SUGGESTIONS_BY_CONTEXT[AI_CONTEXT.general]

/** The suggestions for a context key, always falling back to the general set. */
export function suggestionsFor(context) {
  return SUGGESTIONS_BY_CONTEXT[context] || SUGGESTIONS_BY_CONTEXT[AI_CONTEXT.general]
}

/** Kept for compatibility with any single-list import. */
export const SUGGESTIONS = SUGGESTIONS_BY_CONTEXT[AI_CONTEXT.general]
