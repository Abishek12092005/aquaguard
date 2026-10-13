/**
 * STEP 8 UI check: type into the real Location search bar, keystroke by keystroke.
 *
 * The requirement is that suggestions appear AS THE USER TYPES, across every
 * place kind, from a real provider. So this:
 *   1. types "c" (one character) and checks suggestions appear at all
 *   2. types on to "chennai" and checks the real Chennai leads the list
 *   3. types "karaikudi" and checks the real Karaikudi leads the list
 *   4. types a college, a bank, a pincode and a temple, one after another, and
 *      records the top suggestion for each
 *   5. counts the requests, so "suggestions appear while typing" is not achieved
 *      by firing a request per keystroke and making the user wait for all of them
 *
 * It also records the time to first suggestion, because a list that arrives after
 * the user has finished typing has not solved the problem.
 */
export default async function run(page, ui) {
  const searches = []
  page.on('request', (r) => {
    if (r.url().includes('/locations/search')) {
      searches.push({ q: new URL(r.url()).searchParams.get('q'), at: Date.now() })
    }
  })

  await page.goto('http://localhost:5173/location', { waitUntil: 'domcontentloaded' })
  // Selected by its accessible name, not by its placeholder: the placeholder is
  // the example text ("Karaikudi, 630001, Marina Beach…"), and matching on it
  // would break the moment that copy changes.
  const box = page.getByLabel('Search a location')
  await box.waitFor({ timeout: 30000 })

  const results = {}

  /** Type a query a character at a time and record the first suggestion list. */
  async function probe(label, text) {
    await box.fill('')
    await page.waitForTimeout(400)
    const started = Date.now()
    let firstSuggestionsMs = null
    // Declared out here, not inside the loop: the loop body only counts and
    // clicks, it must not re-create the locator.
    const options = page.locator('#location-suggestions [role="option"]')

    for (const ch of text) {
      await box.type(ch, { delay: 60 })
      if (firstSuggestionsMs === null) {
        const n = await options.count()
        if (n > 0) firstSuggestionsMs = Date.now() - started
      }
    }
    // Let the debounce + lookup settle on the FULL text.
    await options.first().waitFor({ timeout: 30000 })
    const top = await options.first().innerText()
    const count = await options.count()
    results[label] = {
      typed: text,
      topSuggestion: top.replace(/\s+/g, ' ').trim().slice(0, 90),
      suggestionCount: count,
      msToFirstSuggestion: firstSuggestionsMs,
    }
  }

  await probe('single letter "c"', 'c')
  await probe('city "chennai"', 'chennai')
  await probe('town "karaikudi"', 'karaikudi')
  await probe('pincode', '630001')
  await probe('college', 'Thiagarajar College')
  await probe('bank', 'Indian Bank Karaikudi')
  await probe('temple', 'Meenakshi Amman Temple')
  await probe('nagar', 'Anna Nagar')

  return {
    ...results,
    totalSearchRequests: searches.length,
    queriesRequested: searches.map((s) => s.q),
  }
}
