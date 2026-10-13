/**
 * Tests for the context-aware suggested questions.
 *
 *   npm run test:ai
 *
 * These import the REAL modules — `suggestions.js` and the context object — with
 * the `@` alias resolved by a small loader, so a rename or a drifted context key
 * fails the test rather than silently changing what the user sees.
 *
 * What is proved:
 *   1. Each screen offers exactly the documented questions, in order.
 *   2. An unknown context falls back to the general set instead of rendering
 *      nothing.
 *   3. Every suggestion is a non-empty string, so nothing renders as a blank
 *      pill that sends an empty message.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

// Resolve the project's `@/...` alias for plain Node, and transform the JSX
// provider so it can be imported. Registered before any project import.
//
// `register` (async hooks) rather than `registerHooks` (sync): the sync variant
// demands an explicit `shortCircuit: true` on every hook return, and the hooks
// here already follow the async contract.
register('./aliasLoader.mjs', import.meta.url)

const { AI_CONTEXT } = await import('@/context/aquaAIContextObject')
const { suggestionsFor, SUGGESTIONS_BY_CONTEXT } = await import(
  '@/components/AquaAI/suggestions'
)

const EXPECTED = {
  dashboard: [
    'What is my latest prediction?',
    'Explain my dashboard.',
    'Show my recent alerts.',
  ],
  prediction: [
    'What is pH?',
    'How does the prediction work?',
    'What does confidence mean?',
  ],
  predictionResult: [
    'Explain this result.',
    'What does this prediction mean?',
    'Show my history.',
  ],
  history: [
    'Explain my latest prediction.',
    'How many unsafe predictions do I have?',
  ],
  alerts: ['Explain this alert.', 'What is my latest prediction?'],
}

test('every screen offers its documented questions, in order', () => {
  for (const [key, expected] of Object.entries(EXPECTED)) {
    const actual = suggestionsFor(AI_CONTEXT[key]).map((s) => s.label)
    assert.deepEqual(actual, expected, `context ${key}`)
  }
})

test('the fallback set is used for an unknown context', () => {
  const fallback = suggestionsFor(AI_CONTEXT.general).map((s) => s.label)
  assert.ok(fallback.length > 0)
  assert.deepEqual(suggestionsFor('not_a_real_screen').map((s) => s.label), fallback)
  assert.deepEqual(suggestionsFor(undefined).map((s) => s.label), fallback)
  assert.deepEqual(suggestionsFor(null).map((s) => s.label), fallback)
})

test('profile reuses the general set', () => {
  assert.deepEqual(
    suggestionsFor(AI_CONTEXT.profile).map((s) => s.label),
    suggestionsFor(AI_CONTEXT.general).map((s) => s.label),
  )
})

test('every suggestion is a usable, sendable question', () => {
  for (const [context, items] of Object.entries(SUGGESTIONS_BY_CONTEXT)) {
    assert.ok(Array.isArray(items) && items.length > 0, `${context} has suggestions`)
    for (const item of items) {
      assert.equal(typeof item.label, 'string', `${context} label is a string`)
      assert.ok(item.label.trim().length > 0, `${context} label is non-empty`)
      assert.equal(typeof item.icon, 'string', `${context} icon path is a string`)
      assert.ok(item.icon.length > 0, `${context} icon path is non-empty`)
    }
    // Labels are unique within a set, so React keys and click targets differ.
    const labels = items.map((i) => i.label)
    assert.equal(new Set(labels).size, labels.length, `${context} labels are unique`)
  }
})

test('the context keys the sets are keyed by all exist', () => {
  for (const key of Object.keys(EXPECTED)) {
    assert.equal(
      typeof AI_CONTEXT[key],
      'string',
      `AI_CONTEXT.${key} must be defined`,
    )
  }
  assert.equal(AI_CONTEXT.predictionResult, 'prediction_result')
})

test("the documented deterministic phrasings are offered somewhere", () => {
  // These two are resolved server-side by the backend routers, so they must be
  // reachable from a suggestion — otherwise the deterministic path is unused.
  const all = Object.values(SUGGESTIONS_BY_CONTEXT).flat().map((s) => s.label)
  assert.ok(all.includes('Explain my latest prediction.'), 'history offers the tool phrase')
  assert.ok(all.includes('Show my history.'), 'post-prediction offers navigation')
})
