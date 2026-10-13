/**
 * Tests for the location-permission state vocabulary.
 *
 *   npm run test:ai
 *
 * These import the REAL modules with the `@` alias resolved by the same loader
 * the suggestion tests use, so a rename or a drifted status name fails the test
 * rather than silently changing what a screen renders.
 *
 * What is proved, for EVERY permission state the brief names:
 *   1. Each browser `PositionError.code` maps to the documented name — a refusal
 *      is not flattened into "unavailable", and a timeout is its own answer.
 *   2. An unknown / missing code degrades to POSITION_UNAVAILABLE rather than
 *      throwing or being mislabelled as a refusal.
 *   3. The status vocabulary used by the provider and the popup is complete and
 *      stable, so a caller can compare against names rather than bare strings.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

// Registered before any project import — same loader the suggestion tests use.
register('./aliasLoader.mjs', import.meta.url)

const { LOCATION_STATUS, normaliseGeoErrorCode } = await import(
  '@/context/deviceLocationContextObject'
)

test('every browser error code maps to its documented permission state', () => {
  // 1 DENIED, 2 UNAVAILABLE, 3 TIMEOUT — the three the Geolocation API defines.
  assert.equal(normaliseGeoErrorCode(1), 'PERMISSION_DENIED')
  assert.equal(normaliseGeoErrorCode(2), 'POSITION_UNAVAILABLE')
  assert.equal(normaliseGeoErrorCode(3), 'TIMEOUT')
})

test('a refusal is never reported as merely unavailable', () => {
  // The whole point of the mapping: these must not collapse into one another.
  assert.notEqual(normaliseGeoErrorCode(1), normaliseGeoErrorCode(2))
  assert.notEqual(normaliseGeoErrorCode(1), normaliseGeoErrorCode(3))
})

test('an unknown or missing code degrades to POSITION_UNAVAILABLE', () => {
  for (const value of [undefined, null, 0, 99, 'x', {}]) {
    assert.equal(normaliseGeoErrorCode(value), 'POSITION_UNAVAILABLE')
  }
})

test('the status vocabulary covers every state the flow can be in', () => {
  assert.deepEqual(LOCATION_STATUS, {
    idle: 'idle',
    prompting: 'prompting',
    locating: 'locating',
    granted: 'granted',
    denied: 'denied',
    unsupported: 'unsupported',
  })
})
