export default async function run(page, ui) {
  // 1. Login
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill('step32final@aquaguard.test')
  await page.locator('#password').fill('Str0ngPass!2026')
  await page.locator('button[type=submit]').last().click()
  await page.waitForURL(/dashboard|home/i, { timeout: 20000 }).catch(() => { })
  await page.waitForTimeout(1200)

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://localhost:5173/reports', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=Water Quality Report', { timeout: 25000 }).catch(() => { })
  await page.waitForTimeout(800)

  const results = {}

  // Capture the currently selected report's ID from the sheet header.
  const selectedIdText = await page
    .locator('.print-sheet header .font-mono')
    .first()
    .innerText()
    .catch(() => null)
  results.selectedReportId = selectedIdText

  async function openOptionsModal() {
    await page.getByRole('button', { name: /Reports to Mail/i }).first().click()
    await page.waitForTimeout(400)
    await page.locator('#reports-mail-email').fill('user@example.com')
    await page.getByRole('button', { name: 'Enter', exact: true }).click()
    await page.waitForTimeout(500)
    return page.locator('[aria-labelledby="reports-mail-options-title"]')
  }

  // CASE A: a report IS selected (default = newest row)
  const modal = await openOptionsModal()

  // Single-report options usable; the two ALL options too.
  const radios = page.locator('input[name="reports-mail-option"]')
  const disabledFlags = []
  for (let i = 0; i < 4; i++) disabledFlags.push(await radios.nth(i).isDisabled())
  results.caseA_disabledFlags = disabledFlags // expect [false,false,false,false]

  // Choose "Download Report PDF" and Send -> real PDF prepared, NO download
  const downloadEvents = []
  page.on('download', (d) => downloadEvents.push(d.suggestedFilename()))
  await radios.nth(0).check()
  const sendButton = page.getByRole('button', { name: 'Send', exact: true })
  await sendButton.click()
  await page.waitForTimeout(3000) // jsPDF loads lazily
  let text = await modal.innerText()
  results.caseA_pdf = {
    prepared: /PDF attachment for report/.test(text),
    mentionsSelectedId: selectedIdText ? text.includes(selectedIdText) : false,
    byteCount: (text.match(/(\d+) bytes/) || [])[1] || null,
    notSent: /Sending is not enabled yet/.test(text),
    downloadsTriggered: downloadEvents.length,
  }

  // Choose "Download Report CSV" and Send -> real CSV prepared
  await radios.nth(1).check()
  await sendButton.click()
  await page.waitForTimeout(800)
  text = await modal.innerText()
  results.caseA_csv = {
    prepared: /CSV attachment for report/.test(text),
    mentionsSelectedId: selectedIdText ? text.includes(selectedIdText) : false,
    charCount: (text.match(/(\d+) characters/) || [])[1] || null,
    downloadsTriggered: downloadEvents.length, // must still be 0
  }

  // Close everything for CASE B
  await modal.getByRole('button', { name: 'Close', exact: true }).click()
  await page.waitForTimeout(300)

  // CASE B: NO report selected — filter to a risk with ZERO rows ("Unsafe" may
  // have rows; instead clear rows by picking a filter value with 0 count).
  // Safer: choose the chip whose count is 0; if none, skip case B gracefully.
  const chipTexts = await page.locator('button[aria-pressed]').allInnerTexts()
  const zeroChipIndex = chipTexts.findIndex((t) => /\b0\s*$/.test(t.trim()))
  results.caseB_chipFound = zeroChipIndex >= 0
  if (zeroChipIndex >= 0) {
    await page.locator('button[aria-pressed]').nth(zeroChipIndex).click()
    await page.waitForTimeout(500)
    const modalB = await openOptionsModal()
    const textB = await modalB.innerText()
    results.caseB = {
      messageShown: textB.includes('Please select a report first.'),
      reportPdfDisabled: await radios.nth(0).isDisabled(),
      reportCsvDisabled: await radios.nth(1).isDisabled(),
      allPdfEnabled: !(await radios.nth(2).isDisabled()),
      allCsvEnabled: !(await radios.nth(3).isDisabled()),
      sendDisabled: await page.getByRole('button', { name: 'Send', exact: true }).isDisabled(),
      canStillPickAll: true,
    }
    // Pick "Download All PDF" -> Send enabled -> works with no selection
    await radios.nth(2).check()
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await page.waitForTimeout(500)
    const textB2 = await modalB.innerText()
    results.caseB.allOptionStillWorks = /selected for/.test(textB2)
    await modalB.getByRole('button', { name: 'Close', exact: true }).click()
    await page.waitForTimeout(300)
  }

  // Restore default filter (All readings) and confirm the page is intact
  await page.locator('button[aria-pressed]').first().click()
  await page.waitForTimeout(500)
  const body = await page.locator('body').innerText()
  results.pageIntact =
    body.includes('Download all as PDF') && body.includes('Download all CSV') && body.includes('Readings')

  return results
}
