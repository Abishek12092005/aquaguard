/**
 * The honest-failure check, in the real UI: stop the backend mid-flight and
 * confirm the screen says so.
 *
 * The requirement is specific — a genuinely unavailable backend must show a
 * proper error, never a fabricated result. So this asserts three things:
 *   1. an error banner appears
 *   2. NO verdict is rendered (no "safe"/"unsafe", no prediction id)
 *   3. the panel returns to the empty state rather than a stale previous verdict
 * It also submits a second time afterwards to prove the form is still usable.
 */
export default async function run(page, ui) {
  const readings = {
    ph: '7.1', turbidity: '1.2', tds: '280',
    temperature: '18', dissolved_oxygen: '8.4',
  }

  // --- 1. A real prediction first, so there is a verdict that could go stale --
  await page.fill('#ph', readings.ph)
  await page.fill('#turbidity', readings.turbidity)
  await page.fill('#tds', readings.tds)
  await page.fill('#temperature', readings.temperature)
  await page.fill('#dissolved_oxygen', readings.dissolved_oxygen)
  await page.getByRole('button', { name: /Analyze Water Quality/i }).click()
  await page.waitForSelector('text=/Saved as prediction #/i', { timeout: 20000 })
  const firstVerdictShown = (await page.locator('text=/^SAFE$|^MODERATE$|^UNSAFE$/i').count()) > 0

  // --- 2. Break API calls from the browser, then resubmit -------------------
  // Only requests carrying the app's JSON POST body are aborted. A broad
  // `**/api/**` pattern also matches Vite's own `/src/api/index.js` module
  // request, which kills the page rather than the backend.
  const isPredictCall = (r) =>
    r.method() === 'POST' && r.url().includes('/predictions/predict')
  await page.route('**/*', (route) =>
    isPredictCall(route.request()) ? route.abort('connectionrefused') : route.continue(),
  )
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForSelector('#ph', { timeout: 20000 })
  for (const [id, value] of Object.entries(readings)) await page.fill(`#${id}`, value)
  await page.getByRole('button', { name: /Analyze Water Quality/i }).click()

  await page.waitForSelector('[role="alert"]', { timeout: 30000 })
  const banner = await page.locator('[role="alert"]').first().innerText()

  const verdictWhileDown = await page.locator('text=/^SAFE$|^MODERATE$|^UNSAFE$/i').count()
  const savedIdShown = await page.locator('text=/Saved as prediction #/i').count()
  const emptyState = await page.locator('text=/No result yet/i').count()

  // --- 3. The form still works --------------------------------------------
  await page.unroute('**/*')
  await page.getByRole('button', { name: /Analyze Water Quality/i }).click()
  await page.waitForSelector('text=/Saved as prediction #/i', { timeout: 25000 })
  const recovered = (await page.locator('text=/^SAFE$|^MODERATE$|^UNSAFE$/i').count()) > 0

  return {
    firstVerdictShown,
    errorBanner: banner.trim(),
    verdictRenderedWhileBackendDown: verdictWhileDown,
    stalePredictionIdShown: savedIdShown,
    emptyStateReturned: emptyState > 0,
    recoveredAfterBackendReturn: recovered,
  }
}
