/**
 * Renders the Reports page and checks the report-building helpers.
 *
 * The page reads prediction history from the API, so the smoke check asserts on
 * the two things that do not need a server: that the module renders a tree at
 * all, and that the pure helpers produce the shapes the CSV and the table depend
 * on. The helpers are where the real logic lives — a wrong normal range or a
 * mis-quoted CSV field would be invisible in a UI check and wrong in the export.
 */
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import Reports, { ReportSheet } from '@/pages/Reports'
import {
  NORMAL_LEVELS,
  PARAMETER_ORDER,
  buildCsv,
  classifyReading,
  normalRangeText,
  predictionId,
  reportCsv,
  reportId,
} from '@/utils/reports'

const results = {}

try {
  const html = renderToStaticMarkup(h(Reports))
  results.page = {
    ok: html.length > 0,
    length: html.length,
    title: html.includes('Reports'),
    printButton: html.includes('Print / save as PDF'),
    csvButton: html.includes('Download CSV'),
    filters: ['All readings', 'Safe', 'Moderate', 'Unsafe'].filter((f) => html.includes(f)),
    // The print masthead: the brand and droplet, and the class that keeps the
    // droplet alive through the print rule that strips decoration.
    masthead: html.includes('AquaGuard AI') && html.includes('Water Quality Report'),
    mastheadDroplet: html.includes('print-keep'),
    printSheetClass: html.includes('print-sheet'),
  }
} catch (error) {
  results.page = { ok: false, error: String(error) }
}

// Render the report sheet DIRECTLY with a known row.
//
// `Reports` itself fetches its rows, and a server render does not run effects, so
// the page can only ever show its empty state here. Rendering the sheet with a
// row is what actually checks the document this page produces.
const SAMPLE_ROW = {
  id: 42,
  ph: 7.2,
  turbidity: 1.4,
  tds: 310,
  temperature: 19,
  dissolved_oxygen: 8.1,
  prediction: 'safe',
  confidence: 0.93,
  created_at: '2026-09-18T17:15:00',
  // Step 9: the stored location a report must now carry.
  location_name: 'Karaikudi',
  location_state: 'Tamil Nadu',
  location_country: 'India',
  water_source_type: 'ground water',
}

try {
  const sheet = renderToStaticMarkup(h(ReportSheet, { row: SAMPLE_ROW }))
  results.sheet = {
    ok: sheet.length > 0,
    length: sheet.length,
    // The centred masthead: brand name, subtitle, and the droplet badge that
    // survives the print rule stripping decoration.
    brand: sheet.includes('AquaGuard AI'),
    subtitle: sheet.includes('Water Quality Report'),
    dropletKept: sheet.includes('print-keep'),
    printSheet: sheet.includes('print-sheet'),
    mastheadCentred: sheet.includes('items-center') && sheet.includes('text-center'),
    // Every field the user asked the report to carry.
    reportId: sheet.includes('AGR-20260918-00042'),
    predictionId: sheet.includes('PRED-00042'),
    verdict: sheet.includes('SAFE'),
    confidence: sheet.includes('93.0%'),
    // The parameter table with normal ranges beside each measured value.
    parameters: ['pH', 'Turbidity', 'Total Dissolved Solids', 'Temperature', 'Dissolved Oxygen'].filter(
      (label) => sheet.includes(label),
    ),
    normalRanges: ['6.5 – 8.5', '0 – 5', '0 – 500', '10 – 25', '6.5 – 9.5'].filter((range) =>
      sheet.includes(range),
    ),
    statusColumn: sheet.includes('Within normal'),
    labCaveat: sheet.includes('not a laboratory'),
    // STEP 9: the report names WHERE the sample came from and its source.
    showsLocation: sheet.includes('Karaikudi') && sheet.includes('Tamil Nadu'),
    showsWaterSource: sheet.includes('ground water'),
    labelsLocation: sheet.includes('Location') && sheet.includes('Water Source'),
  }
} catch (error) {
  results.sheet = { ok: false, error: String(error) }
}

// --- helper behaviour -------------------------------------------------------
results.helpers = {
  // Every parameter has a band, and every band is usable.
  allParametersHaveBands: PARAMETER_ORDER.every((k) => Boolean(NORMAL_LEVELS[k])),
  bandCount: Object.keys(NORMAL_LEVELS).length,
  ranges: Object.fromEntries(PARAMETER_ORDER.map((k) => [k, normalRangeText(k)])),

  // Classification: one case either side of each boundary.
  phNormal: classifyReading('ph', 7.2),
  phLow: classifyReading('ph', 4),
  phHigh: classifyReading('ph', 9.5),
  phMissing: classifyReading('ph', null),

  // Identifiers must be derived, stable, and quoteable.
  reportIdSample: reportId({ id: 7, created_at: '2026-09-18T17:15:00' }),
  predictionIdSample: predictionId({ id: 7 }),

  // CSV: the degree sign must survive, and a comma-bearing note must be quoted.
  csvHasBom: buildCsv(['a'], [['b']]).charCodeAt(0) === 0xfeff,
  csvQuotesCommas: buildCsv(['a'], [['x,y']]).includes('"x,y"'),
  csvEscapesQuotes: buildCsv(['a'], [['say \u0022hi\u0022']]).includes('"say ""hi"""'),
  csvRowCount: buildCsv(['h1', 'h2'], [[1, 2], [3, 4]]).trim().split('\r\n').length,
  // STEP 9: the CSV carries the location and the water source columns too.
  csvHasLocationColumns:
    reportCsv.headers.includes('Location') && reportCsv.headers.includes('Water Source'),
  csvLocationValue: reportCsv.row(SAMPLE_ROW)[reportCsv.headers.indexOf('Location')],
  csvWaterSourceValue: reportCsv.row(SAMPLE_ROW)[reportCsv.headers.indexOf('Water Source')],
}

console.log(JSON.stringify(results, null, 2))
