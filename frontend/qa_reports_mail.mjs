export default async function run(page, ui) {
  // 1. Login
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill('step32final@aquaguard.test')
  await page.locator('#password').fill('Str0ngPass!2026')
  await page.locator('button[type=submit]').last().click()
  await page.waitForURL(/dashboard|home/i, { timeout: 20000 }).catch(() => { })
  await page.waitForTimeout(1500)

  // 2. Reports page
  await page.goto('http://localhost:5173/reports', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)

  const results = {}
  const pageText = await page.locator('body').innerText()

  // Existing functionality still present?
  results.existing = {
    readingsList: pageText.includes('Readings'),
    filterChips: pageText.includes('Show') && pageText.includes('All readings'),
    pdfButton: pageText.includes('Download all as PDF'),
    csvButton: pageText.includes('Download all CSV'),
  }

  // 3. New side action button present?
  const mailButton = page.getByRole('button', { name: /Reports to Mail/i })
  results.mailButtonVisible = await mailButton.count() > 0
  if (!(await mailButton.count())) return results

  // 4. Open the modal
  await mailButton.first().click()
  await page.waitForTimeout(600)
  const modalText = await page.locator('[role=dialog]').innerText().catch(() => '')
  results.modal = {
    opens: modalText.length > 0,
    hasTitle: modalText.includes('Reports to Mail'),
    hasEmailLabel: modalText.includes('Email Address'),
    hasEnterButton: /\bEnter\b/.test(modalText),
    raw: modalText.slice(0, 300),
  }

  // 5. Invalid email -> clear validation message
  const emailInput = page.locator('#reports-mail-email')
  await emailInput.fill('not-an-email')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(400)
  const modalAfterInvalid = await page.locator('[role=dialog]').innerText().catch(() => '')
  results.invalidEmail = {
    errorMessage: modalAfterInvalid.includes('valid email') ||
      modalAfterInvalid.includes('Please enter'),
    messageText: (modalAfterInvalid.match(/[^\n]*valid[^\n]*/i) || [])[0] || null,
  }

  // 6. Empty email -> message too
  await emailInput.fill('')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(300)
  const modalEmpty = await page.locator('[role=dialog]').innerText().catch(() => '')
  results.emptyEmail = modalEmpty.includes('Please enter an email address')

  // 7. Valid email -> accepted, no send
  await emailInput.fill('user@example.com')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(400)
  const modalValid = await page.locator('[role=dialog]').innerText().catch(() => '')
  results.validEmail = {
    accepted: modalValid.includes('looks valid') || modalValid.includes('not enabled yet'),
    text: (modalValid.match(/[^\n]*valid[^\n]*/i) || [])[0] || null,
  }

  // 8. Close via X and confirm the page is unchanged
  await page.getByRole('button', { name: 'Close', exact: true }).click()
  await page.waitForTimeout(400)
  results.modalCloses = (await page.locator('[role=dialog]').count()) === 0
  const finalText = await page.locator('body').innerText()
  results.pageIntactAfterClose =
    finalText.includes('Download all as PDF') && finalText.includes('Readings')

  return results
}
