// STEP 33: the History page's location information, without the emojis.
//
// What is checked, and why each check is here:
//
//   1. NO EMOJI ANYWHERE IN THE PAGE'S OWN TEXT. The "📍" and "💧" characters were
//      OS-DRAWN: the browser picks the glyph, so the same row looked different on
//      every machine. This asserts on the absence of those CHARACTERS, which is
//      the thing that was actually wrong — not on the absence of a pin SHAPE,
//      because the replacement is a pin drawn as SVG.
//
//   2. THE DATA SURVIVED. A "remove the emoji" change that quietly drops a field
//      is the failure this step is most at risk of, since the natural way to do it
//      is to retype the cell. Every location field is asserted present as TEXT,
//      read off the rendered page.
//
//   3. THE DETAIL PANEL. The table cell is only a summary; the full location lives
//      in the panel, so it is opened and checked separately — including that the
//      district row does NOT appear when the record carries no district, which is
//      the normal case for history.
export default async function run(page) {
  const out = {}

  // TWO RECORDS ON PURPOSE. One with an area and a district, one without — the
  // shape every history row read back from the database actually has, since
  // `location_district` is not a stored column and arrives only on the predict
  // response. A stub with a district everywhere would make the "does it cope when
  // the field is absent" question unaskable.
  const ROWS = [
    {
      id: 101, ph: 7.2, turbidity: 2.4, tds: 380, temperature: 26, dissolved_oxygen: 7.8,
      prediction: 'safe', confidence: 0.92,
      location_name: 'Karaikudi', location_city: 'Karaikudi',
      location_area: 'Anna Nagar', location_district: 'Karaikkudi',
      location_state: 'Tamil Nadu', location_country: 'India', location_pincode: '630001',
      water_source_type: 'ground water', nearby_water_source: 'Borewell',
      nearby_water_source_distance: '0.40', created_at: '2026-09-28T10:15:00Z',
    },
    {
      id: 102, ph: 6.1, turbidity: 48.0, tds: 2100, temperature: 31, dissolved_oxygen: 3.1,
      prediction: 'unsafe', confidence: 0.88,
      location_name: 'Marina Beach', location_city: 'Chennai',
      location_area: null, location_district: null,
      location_state: 'Tamil Nadu', location_country: 'India', location_pincode: '600001',
      water_source_type: 'sea water', nearby_water_source: null,
      nearby_water_source_distance: null, created_at: '2026-09-27T14:40:00Z',
    },
  ]

  try {
    const body = (rows) =>
      JSON.stringify({
        success: true,
        data: rows,
        meta: { page: 1, per_page: 20, total: rows.length },
      })

    await page.route('**/predictions/history**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: body(ROWS) }),
    )
    // The detail panel fetches the single record rather than reusing the row.
    await page.route('**/predictions/101**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: ROWS[0] }) }),
    )
    await page.route('**/predictions/102**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: ROWS[1] }) }),
    )

    await page.goto('http://127.0.0.1:5173/history', { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('table tbody tr', { timeout: 90000 })
    await page.waitForTimeout(1500)

    // THE PAGE'S OWN TEXT, not the whole document — the sidebar carries no
    // emoji here, but scoping to <main> is what keeps this check honest if that
    // ever changes, and the browser's own chrome text is not the page's.
    const main = await page.evaluate(() => {
      const el = document.querySelector('main') || document.querySelector('[role="main"]')
      return el ? el.innerText : ''
    })
    out.mainFound = main.length > 0

    // --- 1. NO EMOJI ----------------------------------------------------
    // The specific characters that were removed. Matched as codepoints so this
    // cannot be satisfied by an icon that merely looks like a pin.
    const EMOJI = ['\u{1F4CD}', '\u{1F4A7}'] // 📍 💧
    out.emojiFound = EMOJI.filter((e) => main.includes(e))
    out.noEmoji = out.emojiFound.length === 0

    // A broader sweep for ANY emoji in the location area, so a second one that
    // was already there and not named in the brief cannot survive unnoticed.
    const allEmoji = main.match(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu) || []
    out.anyEmojiOnPage = allEmoji
    out.noEmojiAtAll = allEmoji.length === 0

    // --- 2. THE DATA SURVIVED (table) -----------------------------------
    out.tableHasLocationNames = ['Karaikudi', 'Marina Beach'].every((n) => main.includes(n))
    out.tableHasPincode = main.includes('630001') && main.includes('600001')
    out.tableHasWaterSource = /Ground Water/i.test(main) && /Sea Water/i.test(main)
    out.tableHasArea = main.includes('Anna Nagar')
    out.tableHasDistrict = main.includes('Karaikkudi')
    out.tableHasState = main.includes('Tamil Nadu')
    out.tableHasCountry = main.includes('India')
    // And the row's other columns, so the location change did not disturb them.
    out.tableHasVerdicts = /SAFE|UNSAFE/i.test(main)
    // `formatPercent` is `(value * 100).toFixed(1)` — ONE decimal place, always.
    // A regex of /9[0-9]%/ would never match "92.0%", and would then report the
    // confidence column as missing on a row that plainly shows it.
    out.tableHasConfidence = /9[0-9]\.[0-9]%/.test(main)
    out.tableHasDate = /2026|Sep|2026/.test(main)

    // --- 3. THE DETAIL PANEL --------------------------------------------
    await page.locator('button[aria-label*="View details"]').first().click()
    await page.waitForTimeout(2500)

    const panel = await page.evaluate(() => {
      const dlg = document.querySelector('[role="dialog"]') || document.querySelector('aside')
      return dlg ? dlg.innerText : ''
    })
    out.panelOpened = panel.length > 0
    out.panelNoEmoji = EMOJI.filter((e) => panel.includes(e)).length === 0

    // EVERY FIELD THE BRIEF LISTS, as text, in the panel.
    out.panel = {
      place: /Karaikudi/.test(panel),
      area: /Anna Nagar/.test(panel),
      district: /Karaikkudi/.test(panel),
      state: /Tamil Nadu/.test(panel),
      country: /India/.test(panel),
      pincode: /630001/.test(panel),
      waterSource: /Ground Water/i.test(panel),
      nearestSource: /Borewell/.test(panel),
      parameters: /pH/i.test(panel) && /Turbidity/i.test(panel) && /Dissolved Oxygen/i.test(panel),
      prediction: /SAFE/i.test(panel),
      // THE PANEL FORMATS CONFIDENCE TO ZERO DECIMALS (`formatPercent(x, 0)`),
      // while the TABLE formats it to one. So this is /92%/ and not /92.0%/ —
      // matching the table's shape here would report a confidence that is plainly
      // on screen as missing.
      confidence: /92%|9[0-9]%/.test(panel),
      dateTime: /2026|Sep/.test(panel),
    }

    // The ICON is not the label: every row still carries a real word, so the
    // picture is never the only thing identifying a field.
    out.panelLabels = ['Place', 'Area', 'District', 'State', 'Country', 'Pincode', 'Water Source'].filter((l) =>
      panel.includes(l),
    )

    // Icons, not characters: the location list must now contain inline SVG.
    out.panelHasSvg = await page.evaluate(() => {
      const dlg = document.querySelector('[role="dialog"]') || document.querySelector('aside')
      if (!dlg) return false
      return dlg.querySelectorAll('svg').length
    })

    // --- 4. A ROW WITH NO DISTRICT AND NO AREA ---------------------------
    // The panel must cope: no empty "District" row, and no invented value.
    //
    // The panel is CLOSED first. It is a full-screen overlay, so the second row's
    // "View" button sits underneath it and the click lands on the backdrop — which
    // closes the panel and opens nothing. The result reads as every field being
    // absent on that row, which is a click-occlusion problem in the check rather
    // than a data bug, and it is exactly the kind of thing that gets "fixed" by
    // editing the app instead of the check.
    await page.getByRole('button', { name: /^Close$/ }).click().catch(() => {})
    await page.waitForTimeout(1200)
    await page.locator('button[aria-label*="View details"]').nth(1).click()
    await page.waitForTimeout(2500)
    const panel2 = await page.evaluate(() => {
      const dlg = document.querySelector('[role="dialog"]') || document.querySelector('aside')
      return dlg ? dlg.innerText : ''
    })
    // The panel must cope: no empty "District" row, and no invented value.
    out.secondPanelHasPlace = /Marina Beach/.test(panel2)
    // "District" must be ABSENT, not present-and-blank: printing the label with no
    // value is the "shows a gap that was never there" failure.
    out.secondPanelOmitsDistrict = !/District/.test(panel2)
    out.secondPanelOmitsArea = !/\bArea\b/.test(panel2)
    out.secondPanelKeepsPincode = /600001/.test(panel2)
    out.secondPanelKeepsSource = /Sea Water/i.test(panel2)
    out.secondPanelNoBlankRow = !/\bArea:\s*$/m.test(panel2)
  } catch (e) {
    out.error = String(e).slice(0, 300)
  }
  return out
}
