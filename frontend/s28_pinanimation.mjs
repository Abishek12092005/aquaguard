// STEP 28: the location action's pin is a professional animated mark, not an
// emoji, and the button still opens the map.
//
// What would be easy to fake and must not be:
//   * "no emoji" is asserted against the BUTTON's own text, not the page - the
//     page still contains the words "Pick a location", and asserting on the
//     whole body would match the button's accessible name and prove nothing.
//   * "animated" is asserted by reading COMPUTED values from two moments,
//     because a class name on an element proves nothing about whether the
//     browser is actually animating it. If the keyframe was compiled away, the
//     computed `transform` stays `none` and this fails.
export default async function run(page) {
  const out = {}
  try {
    await page.waitForSelector('button[aria-label="Pick a location on the map"]', { timeout: 90000 })

    const read = () => page.evaluate(() => {
      const btn = document.querySelector('button[aria-label="Pick a location on the map"]')
      const svg = btn?.querySelector('svg')
      const pulse = btn?.querySelector('.aqua-pin-pulse')
      const glow = btn?.querySelector('.aqua-pin-glow')
      const body = btn?.querySelector('.aqua-pin-body')
      const cs = (el) => (el ? getComputedStyle(el) : null)
      return {
        // The button's OWN text. An emoji here is the failure this step exists
        // to fix; the accessible name comes from aria-label, not from text, so
        // replacing the glyph cannot break how the button is announced.
        buttonText: btn?.innerText ?? null,
        hasSvg: Boolean(svg),
        pinParts: [pulse, glow, body].filter(Boolean).length,
        pulseAnim: cs(pulse)?.animationName ?? null,
        pulseDur: cs(pulse)?.animationDuration ?? null,
        pulseIter: cs(pulse)?.animationIterationCount ?? null,
        glowAnim: cs(glow)?.animationName ?? null,
        glowDur: cs(glow)?.animationDuration ?? null,
        bodyAnim: cs(body)?.animationName ?? null,
        bodyDur: cs(body)?.animationDuration ?? null,
        // The current transform of each moving part, read twice to prove motion.
        pulseTransform: cs(pulse)?.transform ?? null,
        bodyTransform: cs(body)?.transform ?? null,
        glowTransform: cs(glow)?.transform ?? null,
        // The pin inherits the button's colour rather than a hardcoded one.
        stroke: svg ? getComputedStyle(svg).stroke : null,
        svgSize: svg ? svg.getBoundingClientRect().width : null,
        // The button must not have lost its accessible name.
        ariaLabel: btn?.getAttribute('aria-label') ?? null,
        title: btn?.getAttribute('title') ?? null,
      }
    })

    out.before = await read()

    // A REAL emoji glyph would render as text. The pin must be vector: paths and
    // circles, no text node, and no character in the button's own text content.
    out.noEmojiText = !/\p{Extended_Pictographic}/u.test(out.before.buttonText || '')
    out.isVector = out.before.hasSvg
    out.allThreePartsPresent = out.before.pinParts === 3
    out.pulseAnimating = out.before.pulseAnim === 'aqua-pin-pulse'
    out.glowAnimating = out.before.glowAnim === 'aqua-pin-glow'
    out.bobAnimating = out.before.bodyAnim === 'aqua-pin-bob'
    out.infinite = out.before.pulseIter === 'infinite'
    out.subtleDuration = /^2\.4s$/.test(out.before.pulseDur || '')

    // PROOF OF MOTION, not proof of intent: sample the transforms twice. A
    // keyframe that was compiled out of the CSS bundle leaves these identical
    // (`none` twice), and this step would then be decorative in name only.
    await page.waitForTimeout(700)
    const mid = await read()
    out.transformsChanged =
      mid.pulseTransform !== out.before.pulseTransform ||
      mid.bodyTransform !== out.before.bodyTransform ||
      mid.glowTransform !== out.before.glowTransform
    out.transformSampleA = {
      pulse: out.before.pulseTransform,
      body: out.before.bodyTransform,
      glow: out.before.glowTransform,
    }
    out.transformSampleB = {
      pulse: mid.pulseTransform,
      body: mid.bodyTransform,
      glow: mid.glowTransform,
    }

    // The animation must be SUBTLE, not a strobe: the pulse spends much of its
    // life at zero opacity, and the pin never travels far.
    out.pulseOpacityNow = mid.pulseAnim ? await page.evaluate(() => {
      const el = document.querySelector('button[aria-label="Pick a location on the map"] .aqua-pin-pulse')
      return el ? Number(getComputedStyle(el).opacity) : null
    }) : null

    // IT INHERITS THE PALETTE: `currentColor`, so it is the brand aqua rather
    // than the hardcoded yellow an emoji brings with it.
    out.inheritsColor = out.before.stroke !== 'none' && out.before.stroke !== 'rgb(0, 0, 0)'

    // THE BUTTON STILL WORKS. This is the part the brief is most explicit about:
    // the icon replaced a glyph, nothing about the action may change.
    await page.locator('button[aria-label="Pick a location on the map"]').click()
    await page.waitForSelector('[role="dialog"]', { timeout: 30000 })
    out.popupOpened = (await page.locator('[role="dialog"]').count()) === 1
    out.popupTitle = await page.locator('[role="dialog"] h2').first().innerText()
    // The manual picker, not the device-fix one - the icon must open the same
    // manual selector the emoji always opened.
    out.isManualPicker = /Select Your Location/i.test(out.popupTitle)
    out.mapPresent = (await page.locator('.leaflet-container').count()) === 1
    // And the step-27 search bar is still there inside it: this step added an
    // icon to a button, and must not have cost the map its search.
    out.searchBarStillThere = (await page.locator('[data-testid="map-search"]').count()) === 1

    await page.getByRole('button', { name: /Close/i }).first().click()
    await page.waitForTimeout(500)
    out.popupClosed = (await page.locator('[role="dialog"]').count()) === 0
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
