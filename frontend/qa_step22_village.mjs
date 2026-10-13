/**
 * STEP 22 gate: a BARE VILLAGE NAME must not produce a water-quality result.
 *
 * This checks the rule the brief states, end to end against the real backend:
 *
 *   VILLAGES      "ExampleVillage" alone            -> REFUSED, district required
 *   VILLAGES      "ExampleVillage, SomeDistrict"    -> allowed through
 *   EVERYTHING    cities, towns, areas, nagar, colonies, companies, shops,
 *                 colleges, schools, hotels, hospitals, landmarks
 *                                                    -> NORMAL, never restricted
 *
 * Run: node qa_step22_village.mjs            (backend must be up)
 *
 * The API half always runs. The browser half needs Playwright, which is not a
 * dependency of this project, so it is skipped with a note rather than failing
 * the gate - the API checks are the enforcement, this screen only renders it.
 */
const BASE = process.env.BASE_URL || 'http://localhost:5199'
const API = process.env.API_URL || 'http://127.0.0.1:5000'
const TOKEN = process.env.TOKEN || ''

/** Playwright, or null when it is not installed. */
let chromium = null
try {
  ;({ chromium } = await import('playwright'))
} catch {
  chromium = null
}

/** Ask the resolver directly and report what the backend decided. */
async function ask(q) {
  const url = `${API}/api/v1/locations/resolve?q=${encodeURIComponent(q)}`
  const res = await fetch(url, { headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {} })
  const body = await res.json().catch(() => ({}))
  const data = body?.data ?? {}
  return {
    q,
    status: res.status,
    // requires_district is the gate's own flag; the frontend keys off it.
    restricted: data?.requires_district === true,
    reason: data?.reason ?? null,
    candidates: Array.isArray(data?.candidates) ? data.candidates.length : null,
    isPlace: Boolean(data?.name) && data?.requires_district !== true,
  }
}

const VILLAGE = process.env.VILLAGE || 'Kothanallur'
const DISTRICT = process.env.DISTRICT || 'Kalkulam'

const VILLAGE_CASES = [
  { q: VILLAGE, expectRestricted: true },
  { q: `${VILLAGE}, ${DISTRICT}`, expectRestricted: false },
  { q: `${VILLAGE}, ${DISTRICT}, Tamil Nadu`, expectRestricted: false },
  // A name several villages answer to - the ambiguity the brief calls out.
  { q: 'Kottur', expectRestricted: true },
]

/** Everything the brief says must keep working normally. */
const NON_VILLAGE_CASES = [
  'Chennai', 'Karaikudi', 'Coimbatore', 'Kochi',
  // "Anna Nagar" is the case that proves the rule is not merely "the word
  // appears in some row". Nominatim leads with the real nagar (a suburb) and
  // only lists unrelated villages of the same name further down, so this must
  // NOT be gated - a nagar is on the brief's exemption list.
  'Anna Nagar', 'T Nagar', 'K K Nagar', 'Green Park Colony',
  // "Athur" and "Chettikulam" are villages by name and also lead with a SUBURB
  // in the map data. A suburb is an area, and areas are exempt, so the
  // provider's own ranking decides these and they are searched normally. These
  // are the sharpest cases in the set: the rule follows the map's best answer,
  // not the shape of the name.
  'Athur', 'Chettikulam', 'Athur, Chengalpattu',
  'HDFC Bank', 'Reliance Fresh', 'Kumaraguru College', 'Delhi Public School',
  'Taj Hotel', 'Apollo Hospital', 'Marina Beach', 'Meenakshi Amman Temple',
  '630001',
].map((q) => ({ q, expectRestricted: false }))

async function uiCheck() {
  if (!chromium) return { skipped: 'playwright not installed' }
  const browser = await chromium.launch()
  const page = await browser.newPage()
  // Search a bare village name: the disambiguation card must appear, and no
  // water-quality result may be rendered behind it.
  await page.goto(`${BASE}/location`, { waitUntil: 'domcontentloaded' })
  const box = page.locator('input[type="text"]').first()
  await box.click()
  await box.fill(VILLAGE)
  await box.press('Enter')
  await page.waitForTimeout(9000)

  const read = await page.evaluate(() => {
    const t = document.body.innerText
    return {
      asksForDistrict: /district/i.test(t) && /which|select|enter|identify/i.test(t),
      hasWaterResult: /Selected location|Water Source|Source type|SAFE|MODERATE|UNSAFE/i.test(t),
      candidateRows: document.querySelectorAll('[data-testid="village-candidates"] li').length,
    }
  })
  await browser.close()
  // The gate holds when the district is requested and no result is shown.
  return { ...read, pass: read.asksForDistrict && !read.hasWaterResult }
}

const browserResults = []
for (const c of [...VILLAGE_CASES, ...NON_VILLAGE_CASES]) {
  try {
    const r = await ask(c.q)
    browserResults.push({ ...c, ...r, pass: r.restricted === c.expectRestricted })
  } catch (err) {
    browserResults.push({ ...c, error: String(err), pass: false })
  }
}

try {
  const ui = await uiCheck()
  if (ui.skipped) console.log(`SKIP  (UI) ${ui.skipped}\n`)
  else browserResults.push({ q: '(UI) bare village', ...ui })
} catch (err) {
  browserResults.push({ q: '(UI) bare village', error: String(err), pass: false })
}

for (const r of browserResults) {
  const verdict = r.pass ? 'PASS' : 'FAIL'
  console.log(
    `${verdict}  ${String(r.q).padEnd(34)} restricted=${r.restricted} ` +
      `expected=${r.expectRestricted} status=${r.status ?? '-'} ` +
      `candidates=${r.candidates ?? '-'} ${r.error || ''}`,
  )
}

const failed = browserResults.filter((r) => !r.pass)
console.log(`\n${browserResults.length - failed.length}/${browserResults.length} passed`)
process.exit(failed.length ? 1 : 0)
