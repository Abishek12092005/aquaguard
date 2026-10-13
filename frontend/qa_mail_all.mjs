export default async function run(page, ui) {
  // 1. Login as the account with several reports
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

  // How many reports the account actually has (the subtitle "N records").
  const body0 = await page.locator('body').innerText()
  const subtitle = (body0.match(/(\d+) records?/) || [])[1] || null

  const results = { accountReportCount: subtitle }

  // 2. Open the mail modal -> valid email -> options popup
  await page.getByRole('button', { name: /Reports to Mail/i }).first().click()
  await page.waitForTimeout(400)
  await page.locator('#reports-mail-email').fill('user@example.com')
  await page.getByRole('button', { name: 'Enter', exact: true }).click()
  await page.waitForTimeout(500)
  const modal = page.locator('[aria-labelledby="reports-mail-options-title"]')
  const radios = page.locator('input[name="reports-mail-option"]')
  const sendButton = page.getByRole('button', { name: 'Send', exact: true })

  // Track any file downloads — none may be triggered by Send.
  const downloadEvents = []
  page.on('download', (d) => downloadEvents.push(d.suggestedFilename()))
  // Track API calls that could email — none expected.
  const apiPosts = []
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes('/api/')) apiPosts.push(req.url())
  })

  // 3. "Download All PDF" -> Send -> one PDF with ALL the account's reports
  await radios.nth(2).check()
  await sendButton.click()
  await page.waitForTimeout(4000) // jsPDF loads lazily; multi-page render
  let text = await modal.innerText()
  results.allPdf = {
    prepared: /PDF attachment with all/.test(text),
    countMentioned: text.includes(`all ${subtitle} of your reports`),
    byteCount: (text.match(/(\d+) bytes/) || [])[1] || null,
    notSent: /Sending is not enabled yet/.test(text),
  }

  // 4. "Download All CSV" -> Send -> one CSV with ALL the account's reports
  await radios.nth(3).check()
  await sendButton.click()
  await page.waitForTimeout(800)
  text = await modal.innerText()
  results.allCsv = {
    prepared: /CSV attachment with all/.test(text),
    countMentioned: text.includes(`all ${subtitle} of your reports`),
    charCount: (text.match(/(\d+) characters/) || [])[1] || null,
    notSent: /Sending is not enabled yet/.test(text),
  }

  results.noDownloadsTriggered = downloadEvents.length === 0
  results.noApiPosts = apiPosts.length === 0

  // 5. Close -> page intact
  await modal.getByRole('button', { name: 'Close', exact: true }).click()
  await page.waitForTimeout(400)
  const body = await page.locator('body').innerText()
  results.pageIntact =
    body.includes('Download all as PDF') &&
    body.includes('Download all CSV') &&
    body.includes('Readings') &&
    (await page.locator('[role=dialog]').count()) === 0

  return results
}
