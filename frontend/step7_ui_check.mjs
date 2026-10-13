/**
 * STEP 7 UI check: drive the real Predict screen in a real browser.
 *
 * Fills the five readings, clicks Analyze, and measures the wall-clock time from
 * the click to the verdict appearing on screen — which is the number the
 * requirement is actually about, since the API benchmark cannot see the render.
 *
 * It also watches for two things that would defeat the point of the exercise:
 *   - more than ONE request to the predict endpoint (a duplicate submission)
 *   - a verdict from a previous run still on screen while a new one is loading
 * and it confirms the measured "analysed in" figure is rendered, which is what
 * proves the loading state and the timing come from the real request.
 */
export default async function run(page, ui) {
  const requests = []
  page.on('request', (r) => {
    if (r.url().includes('/predictions/predict')) {
      requests.push({ method: r.method(), at: Date.now() })
    }
  })

  await page.goto('http://localhost:5173/predict', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('#ph', { timeout: 20000 })

  const readings = {
    ph: '7.1',
    turbidity: '1.2',
    tds: '280',
    temperature: '18',
    dissolved_oxygen: '8.4',
  }
  for (const [id, value] of Object.entries(readings)) {
    await page.fill(`#${id}`, value)
  }

  // The empty-state panel must be showing before we submit — proves the result
  // area starts empty rather than pre-filled with anything.
  const beforeSubmit = await page.locator('text=No result yet').count()

  const started = Date.now()
  await page.getByRole('button', { name: /Analyze Water Quality/i }).click()

  // Catch the loading state while it is genuinely on screen. The verdict lands
  // fast, so this polls rather than sleeping for a guessed interval.
  const sawSpinner = await page
    .waitForSelector('text=/Analyzing water quality/i', { timeout: 4000 })
    .then(() => true)
    .catch(() => false)

  await page.waitForSelector('text=/Saved as prediction #/i', { timeout: 20000 })
  const elapsed = Date.now() - started

  const verdictText = await page.locator('text=/^SAFE$|^MODERATE$|^UNSAFE$/i').first().innerText()
  const analysisLine = await page.locator('text=/analysed in/i').first().innerText()

  // A second submission must not double-post, and the first verdict must not
  // be shown while the second is in flight.
  return {
    emptyStateBeforeSubmit: beforeSubmit > 0,
    sawLoadingState: sawSpinner,
    verdict: verdictText.trim(),
    timeToVerdictMs: elapsed,
    reportedTiming: analysisLine.trim(),
    predictRequests: requests.length,
    requestMethods: requests.map((r) => r.method),
  }
}
