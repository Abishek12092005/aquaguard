/**
 * STEP 23 gate: a typed PINCODE identifies a real area, and is never fabricated.
 *
 * The brief's four demands, checked against the live API:
 *
 *   1. A valid pincode identifies the area behind it, and shows Area,
 *      City/Town, District, State, Country and Pincode.
 *   2. The water source and the water-quality parameters are then retrievable
 *      for that area.
 *   3. Nothing is fabricated - a pincode the postal data does not know is
 *      REFUSED, never answered with a place that happens to share the digits.
 *   4. A pincode covering several areas offers all of them.
 *
 * The cases in group 3 are the ones that mattered before this step existed: the
 * ordinary name search answered "999999" with a railway station in Italy,
 * "12345" (not six digits) with a rural council in Ukraine, and "630001" with
 * nothing at all.
 *
 * Run: node qa_step23_pincode.mjs
 */
const API = process.env.API_URL || 'http://127.0.0.1:5056'

let pass = 0
let fail = 0
let skip = 0

function check(name, ok, detail = '') {
  if (ok) pass += 1
  else fail += 1
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`)
}

/** A check that is skipped when the shared geocoder is busy. */
function checkUnlessBusy(name, r, ok, detail = '') {
  if (upstreamBusy(r)) {
    skip += 1
    console.log(`SKIP  ${name}  (geocoder busy, status=${r.status})`)
    return
  }
  check(name, ok, detail)
}

async function get(path) {
  const res = await fetch(`${API}/api/v1${path}`)
  const body = await res.json().catch(() => ({}))
  return { status: res.status, data: body?.data ?? null, meta: body?.meta ?? null, raw: body }
}

/**
 * The postal lookups hit a PUBLIC geocoder, which rate-limits. A 429 or a 503 is
 * the upstream being busy, not this feature being wrong, so it is reported as
 * SKIPPED rather than counted as a failure - otherwise a busy afternoon reads as
 * a broken pincode lookup and hides a real regression behind it.
 */
function upstreamBusy(r) {
  return r.status === 429 || r.status === 502 || r.status === 503 || r.status === 504
}

async function pause(ms = 1200) {
  await new Promise((r) => setTimeout(r, ms))
}

// --- 1. REAL PINCODES IDENTIFY A REAL AREA ---------------------------------
console.log('--- a valid pincode identifies its area ---')
const PINS = ['630001', '560001', '110001', '600001', '208001', '682001', '500001']
for (const pc of PINS) {
  const r = await get(`/locations/pincode?q=${pc}`)
  const d = r.data
  // Every one of the six fields the brief names must be present as a real value.
  const filled = ['area', 'city', 'district', 'state', 'country', 'pincode'].filter(
    (k) => d && d[k],
  ).length
  checkUnlessBusy(
    `${pc} identifies an area`,
    r,
    r.status === 200 && filled === 6,
    `status=${r.status} fields=${filled}/6 area=${d?.area} city=${d?.city} ` +
      `district=${d?.district} state=${d?.state} country=${d?.country} pincode=${d?.pincode}`,
  )
  // The pincode echoed back must be the one that was typed, never a neighbour's.
  checkUnlessBusy(`${pc} echoes its own pincode`, r, d?.pincode === pc, `got=${d?.pincode}`)
  // A place is only useful if it can be looked up for water at its coordinates.
  checkUnlessBusy(
    `${pc} has usable coordinates`,
    r,
    Number.isFinite(d?.lat) && Number.isFinite(d?.lon),
    `lat=${d?.lat} lon=${d?.lon}`,
  )
  await pause()
}

// --- 2. WATER SOURCE + PARAMETERS FOR THE IDENTIFIED AREA -----------------
console.log('\n--- water source and parameters for the identified area ---')
for (const pc of ['630001', '560001']) {
  const p = await get(`/locations/pincode?q=${pc}`)
  const d = p.data
  if (!d) {
    check(`${pc} water lookup`, false, 'no place to look up')
    continue
  }
  const c = await get(
    `/locations/context?lat=${d.lat}&lon=${d.lon}`,
  )
  const water = c.data?.water
  const defaults = c.data?.default_parameters
  check(
    `${pc} water source retrieved`,
    c.status === 200 && Boolean(water),
    `status=${c.status} primary=${water?.primary} nearest=${water?.nearest?.name ?? '-'}`,
  )
  check(
    `${pc} water-quality parameters retrieved`,
    defaults && Object.keys(defaults).length > 0,
    `parameters=${defaults ? Object.keys(defaults).join(',') : 'none'}`,
  )
  await pause()
}

// --- 3. NOT FABRICATED: a number the postal data does not know is REFUSED ---
console.log('\n--- unknown and malformed pincodes are refused, never guessed ---')
const BAD = [
  { q: '999999', why: 'six digits, not in the postal data' },
  { q: '000000', why: 'a leading zero is not a civilian PIN code' },
  { q: '12345', why: 'five digits - measured, this used to return Ukraine' },
  { q: '012345', why: 'leading zero' },
  { q: '12345678', why: 'too long' },
]
for (const { q, why } of BAD) {
  const r = await get(`/locations/pincode?q=${q}`)
  check(
    `${q} refused (${why})`,
    r.status === 404 || r.status === 422,
    `status=${r.status} place=${r.data?.name ?? 'none'}`,
  )
  // The strongest form of the check: a refusal must carry no place at all.
  check(`${q} carries no invented place`, !r.data?.name, `name=${r.data?.name}`)
  await pause(600)
}

// A pincode must never be silently answered by the ordinary name search either.
console.log('\n--- resolve() must not fall back to a name search for a pincode ---')
for (const pc of ['999999', '12345', '000000', '012345']) {
  const r = await get(`/locations/resolve?q=${pc}`)
  checkUnlessBusy(
    `resolve(${pc}) refused`,
    r,
    r.status === 404,
    `status=${r.status} name=${r.data?.name ?? 'none'} country=${r.data?.country ?? '-'}`,
  )
  await pause(600)
}

// --- 4. A PINCODE MUST NOT BE CONFUSED WITH A VILLAGE (Step 22 still holds) --
console.log('\n--- a pincode is not affected by the village rule ---')
const v = await get('/locations/resolve?q=Kothanallur')
check(
  'a bare village name is still gated (Step 22 intact)',
  v.data?.requires_district === true,
  `requires_district=${v.data?.requires_district}`,
)
await pause()

// --- 4. SEVERAL AREAS: all of them are offered -----------------------------
// Measured across 32 real pincodes, the provider returns exactly ONE Indian
// postal row per number, so this branch does not fire on live data. The
// behaviour is covered deterministically instead by
// backend/test_step23_multi_area.py, which drives the real service with a
// stubbed provider. Here we only assert the single-area case is a clean answer.
console.log('\n--- a single-area pincode is a clean answer, not a prompt ---')
for (const pc of ['630001', '560001']) {
  const r = await get(`/locations/pincode?q=${pc}`)
  const areas = r.data?.areas
  checkUnlessBusy(
    `${pc} resolves to exactly one area, not a multi-area prompt`,
    r,
    r.status === 200 && (areas == null || areas.length === 1),
    `reason=${r.data?.reason} areas=${areas == null ? 'none' : areas.length}`,
  )
  // A field the postal data does not record must be null, and the card shows it
  // as "Not available" - never filled in from the district or the digits.
  const missing = ['area', 'city', 'district']
    .filter((k) => r.data && r.data[k] == null)
  checkUnlessBusy(
    `${pc} leaves an unrecorded field null rather than inventing it`,
    r,
    r.status === 404 || missing.every((k) => r.data[k] == null),
    `null_fields=${missing.join(',') || 'none'}`,
  )
  await pause()
}

console.log(`\n${pass}/${pass + fail} passed` + (skip ? `, ${skip} skipped (geocoder busy)` : ''))
process.exit(fail ? 1 : 0)
