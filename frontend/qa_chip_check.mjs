export default async function run(page, ui) {
  await page.goto('http://localhost:5173/login', { waitUntil: 'domcontentloaded' })
  await page.locator('#email').fill('step32final@aquaguard.test')
  await page.locator('#password').fill('Str0ngPass!2026')
  await page.locator('button[type=submit]').last().click()
  await page.waitForURL(/dashboard|home/i, { timeout: 20000 }).catch(() => { })
  await page.waitForTimeout(1200)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://localhost:5173/reports', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const text = await page.locator('body').innerText()
  return {
    showLabel: text.includes('Show'),
    allReadingsChip: text.includes('All readings'),
    safeChip: text.includes('Safe'),
    moderateChip: text.includes('Moderate'),
    unsafeChip: text.includes('Unsafe'),
    reportSheet: text.includes('Water Quality Report'),
  }
}
