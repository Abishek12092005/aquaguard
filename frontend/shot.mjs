export default async function run(page, ui) {
  await page.setViewportSize({ width: 375, height: 420 })
  await page.goto('http://localhost:5199/reports')
  await page.waitForTimeout(2500)
  await page.screenshot({ path: 'shot-mobile.png', clip: { x: 0, y: 0, width: 375, height: 200 } })
  return { ok: true }
}
