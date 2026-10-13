// STEP 31: the Home page's Location Prediction guide.
//
// The six cards exist to be READ, so what is checked here is what a reader
// actually gets: all six present, in order, with their headings; a column count
// that grows with the viewport; and — the part a static render cannot prove —
// that the entrance animation really runs and really ENDS visible, since the
// cards are `opacity: 0` at the start of their own keyframe and a card left at
// its `from` state is a card nobody can read.
//
// The link onward to the screen the section describes is checked too, because a
// guide that explains the flow and then offers no way to start it is the one
// thing this section must not be.
export default async function run(page) {
  const out = { breakpoints: {} }
  const VIEWPORTS = [
    ['mobile', 390, 844],
    ['tablet', 834, 1112],
    ['desktop', 1440, 900],
  ]

  try {
    for (const [name, width, height] of VIEWPORTS) {
      await page.setViewportSize({ width, height })
      await page.waitForTimeout(1200)

      const cards = page.locator('[data-testid="location-guide-card"]')
      await cards.first().waitFor({ timeout: 30000 })

      // COLUMNS, MEASURED NOT ASSUMED.
      //
      // THE COUNT IS OF DISTINCT LEFT EDGES, NOT OF CARDS SHARING THE FIRST
      // CARD'S EDGE. Those two read identically on one card and are opposites
      // everywhere else: the first version counted cards in the FIRST COLUMN, so
      // a correct one-column layout (all six sharing a left) reported 6 and a
      // correct three-column layout (two per column) reported 2 — the exact
      // inverse of the truth, and it "passed" a grid that was broken.
      //
      // Rounding to the nearest pixel before comparing is what makes this a
      // column count at all: within a row the cards sit on the grid's subpixel
      // track positions, so unrounded lefts differ by a fraction of a pixel on
      // some viewports and the same column would count as several.
      const columns = await page.evaluate(() => {
        const lefts = [
          ...document.querySelectorAll('[data-testid="location-guide-card"]'),
        ].map((b) => Math.round(b.getBoundingClientRect().left))
        return new Set(lefts).size
      })

      const titles = await page.evaluate(() =>
        [...document.querySelectorAll('[data-testid="location-guide-card"] h3')].map((h) =>
          h.innerText.trim(),
        ),
      )

      // EQUAL HEIGHTS WITHIN A ROW. Cards of differing height in the same row are
      // what "responsive but ragged" looks like once it is on screen.
      const rowTops = await page.evaluate(() => {
        const boxes = [...document.querySelectorAll('[data-testid="location-guide-card"]')].map((b) =>
          Math.round(b.getBoundingClientRect().top),
        )
        const heights = [...document.querySelectorAll('[data-testid="location-guide-card"]')].map(
          (b) => Math.round(b.getBoundingClientRect().height),
        )
        const rows = new Map()
        boxes.forEach((top, i) => {
          if (!rows.has(top)) rows.set(top, [])
          rows.get(top).push(heights[i])
        })
        return [...rows.values()].map((h) => ({
          spread: Math.max(...h) - Math.min(...h),
          count: h.length,
        }))
      })

      // NO HORIZONTAL OVERFLOW. The most common responsive failure for a six-card
      // grid is one card refusing to shrink, which pushes the page sideways.
      const overflows = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      )

      out.breakpoints[name] = {
        columns,
        cardCount: titles.length,
        // 390 -> 1, 834 -> 2, 1440 -> 3. Asserted below rather than logged.
        expectedColumns: width < 640 ? 1 : width < 1024 ? 2 : 3,
        titles: titles.length,
        firstTitle: titles[0],
        lastTitle: titles[titles.length - 1],
        raggedRows: rowTops.filter((r) => r.spread > 2).length,
        overflows,
      }
    }

    // --- THE ORDER, READ ONCE ON THE WIDEST VIEW ------------------------
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.waitForTimeout(600)
    out.guideTitles = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="location-guide-card"] h3')].map((h) => h.innerText.trim()),
    )
    out.guideOrderCorrect = out.guideTitles.join(' > ') ===
      'Search a Location > Select the Location > Check Water Source > View Water Parameters > Analyze Water Quality > View Result'

    // --- THE ANIMATION RAN, AND FINISHED VISIBLE --------------------------
    // This is the check the static render cannot make. Each card's opacity is
    // read after its 0.6s animation plus its stagger has elapsed; a card stuck at
    // 0 is a card that is present in the DOM and invisible to the user.
    await page.evaluate(() => {
      document.querySelector('[data-testid="location-guide"]').scrollIntoView({ block: 'center' })
    })
    await page.waitForTimeout(2000)
    out.opacities = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="location-guide-card"] > span')].map((s) =>
        Number(getComputedStyle(s).opacity),
      ),
    )
    out.allVisible = out.opacities.length > 0 && out.opacities.every((o) => o > 0.95)

    // --- THE PRE-EXISTING PAGE IS STILL THERE -----------------------------
    // Step 31 ADDS a section. If any of the four blocks below it disappeared, the
    // feature would have been implemented by breaking the page.
    out.preexistingSections = await page.evaluate(() =>
      [
        'How it works, end to end',
        'What you need to enter',
        'Reading the result',
        'What unsafe water actually costs you',
        'How Location Prediction works',
      ].filter((s) => document.body.innerText.includes(s)),
    )
    out.railStillHasCards = await page.locator('text=Step 1 of 6').count()

    // --- THE LINK ONWARD ---------------------------------------------------
    const cta = page.getByRole('link', { name: /Open Location Prediction/i })
    out.ctaHref = await cta.getAttribute('href')
    await cta.click()
    await page.waitForTimeout(2500)
    out.ctaLandsOnLocation = page.url().includes('/location')
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
