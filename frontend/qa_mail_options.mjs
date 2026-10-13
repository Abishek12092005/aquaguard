export default async function run(page, ui) {
  // 1. Login
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill('step32final@aquaguard.test')
  await page.locator('#password').fill('Str0ngPass!2026')
  await page.locator('button[type=submit]').last().click()
  await page.waitForURL(/dashboard|home/i, { timeout: 20000 }).catch(() => { })
  await page.waitForTimeout(1200)

  // 2. Reports page, desktop viewport
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://localhost:5173/reports', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=Water Quality Report', { timeout: 25000 }).catch(() => { })
  await page.waitForTimeout(800)

  const results = {}
  const bodyBefore = await page.locator('body').innerText()
  results.existing = {
    readingsList: bodyBefore.includes('Readings'),
    pdfButtons:
      bodyBefore.includes('Download report as PDF') && bodyBefore.includes('Download all as PDF'),
    csvButtons: bodyBefore.includes('Download all CSV'),
    mailButton: bodyBefore.includes('Reports to Mail'),
  }

  // 3. Open the email-entry modal
  await page.getByRole('button', { name: /Reports to Mail/i }).first().click()
  await page.waitForTimeout(500)
  const emailModal = await page.locator('[role=dialog]').innerText().catch(() => '')
  results.step1Modal = {
    opens: emailModal.includes('Reports to Mail'),
    hasEmailLabel: emailModal.includes('Email Address'),
    hasEnter: /\bEnter\b/.test(emailModal),
  }

  // 4. Invalid email first -> must NOT advance to the options popup
  await page.locator('#reports-mail-email').fill('bad-email')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(400)
  results.invalidBlocksOptions =
    !(await page.getByText('Download Reports to Our Mail').count()) &&
    (await page.locator('#reports-mail-error').innerText().catch(() => '')).includes('valid email')

  // 5. Valid email + Enter -> options popup opens
  await page.locator('#reports-mail-email').fill('user@example.com')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(500)
  const optionsModal = await page
    .locator('[aria-labelledby="reports-mail-options-title"]')
    .innerText()
    .catch(() => '')
  results.optionsModal = {
    opens: optionsModal.includes('Download Reports to Our Mail'),
    titleExact: optionsModal.includes('Download Reports to Our Mail'),
    showsEmail: optionsModal.includes('user@example.com'),
    hasReportPdf: optionsModal.includes('Download Report PDF'),
    hasReportCsv: optionsModal.includes('Download Report CSV'),
    hasAllPdf: optionsModal.includes('Download All PDF'),
    hasAllCsv: optionsModal.includes('Download All CSV'),
    raw: optionsModal.slice(0, 400),
  }

  // 6. Send DISABLED initially
  const sendButton = page.getByRole('button', { name: 'Send', exact: true })
  results.sendDisabledInitially = await sendButton.isDisabled()

  // 7. Select ONE option -> it becomes checked; selecting another moves the check
  const radios = page.locator('input[name="reports-mail-option"]')
  await radios.nth(2).check() // Download All PDF
  await page.waitForTimeout(200)
  const checkedAfterFirst = await page.locator('input[name="reports-mail-option"]:checked').count()
  await radios.nth(0).check() // Download Report PDF
  await page.waitForTimeout(200)
  const checkedAfterSecond = await page.locator('input[name="reports-mail-option"]:checked').count()
  const checkedValue = await page.locator('input[name="reports-mail-option"]:checked').getAttribute('value')
  results.singleSelection = {
    oneCheckedAfterFirst: checkedAfterFirst === 1,
    oneCheckedAfterSecond: checkedAfterSecond === 1,
    checkedValue,
  }

  // 8. Send ENABLED after a selection
  results.sendEnabledAfterSelection = await sendButton.isEnabled()

  // 9. Click Send -> inline acknowledgement, NOTHING sent (no network call)
  const requestLog = []
  page.on('request', (req) => {
    if (!req.url().includes('socket')) requestLog.push(req.method() + ' ' + req.url())
  })
  await sendButton.click()
  await page.waitForTimeout(600)
  const modalAfterSend = await page
    .locator('[aria-labelledby="reports-mail-options-title"]')
    .innerText()
    .catch(() => '')
  results.afterSend = {
    noteShown: modalAfterSend.includes('Sending is not enabled yet'),
    noteText: (modalAfterSend.match(/[^\n]*selected[^\n]*/i) || [])[0] || null,
    apiRequestsFired: requestLog.filter((r) => r.includes('/api/')).length,
  }

  // 10. Close via X -> both popups gone, page intact
  await page
    .locator('[aria-labelledby="reports-mail-options-title"]')
    .getByRole('button', { name: 'Close', exact: true })
    .click()
  await page.waitForTimeout(400)
  results.closeCleanup = {
    dialogsRemaining: await page.locator('[role=dialog]').count(),
    pageIntact:
      (await page.locator('body').innerText()).includes('Download all as PDF') &&
      (await page.locator('body').innerText()).includes('Readings'),
  }

  return results
}
