export default async function run(page, ui) {
  // Register a FRESH account (no predictions at all) to test the no-selection path.
  const email = `nomail${Date.now()}@aquaguard.test`
  await page.goto('http://localhost:5173/register', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(500)
  const inputs = page.locator('input')
  const n = await inputs.count()
  // Register page fields: name, email, password (+confirm?) — fill all inputs.
  const values = ['No Mail Test', email, 'Str0ngPass!2026', 'Str0ngPass!2026']
  for (let i = 0; i < Math.min(n, values.length); i++) {
    await inputs.nth(i).fill(values[i])
  }
  await page.locator('button[type=submit]').last().click()
  await page.waitForURL(/dashboard|home|reports/i, { timeout: 20000 }).catch(() => { })
  await page.waitForTimeout(1200)

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://localhost:5173/reports', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)
  const body = await page.locator('body').innerText()
  const hasZeroReports = body.includes('No readings')

  // Open the mail modal with the fresh (report-less) account.
  await page.getByRole('button', { name: /Reports to Mail/i }).first().click()
  await page.waitForTimeout(400)
  await page.locator('#reports-mail-email').fill('user@example.com')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(500)
  const modal = page.locator('[aria-labelledby="reports-mail-options-title"]')
  const text = await modal.innerText().catch(() => '')
  const radios = page.locator('input[name="reports-mail-option"]')
  return {
    hasZeroReports,
    messageShown: text.includes('Please select a report first.'),
    reportPdfDisabled: await radios.nth(0).isDisabled(),
    reportCsvDisabled: await radios.nth(1).isDisabled(),
    allPdfEnabled: !(await radios.nth(2).isDisabled()),
    allCsvEnabled: !(await radios.nth(3).isDisabled()),
    sendDisabled: await page.getByRole('button', { name: 'Send', exact: true }).isDisabled(),
    existingButtonsIntact:
      body.includes('Download all as PDF') && body.includes('Download all CSV'),
  }
}
