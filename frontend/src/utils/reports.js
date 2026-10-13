/**
 * Report helpers: normal ranges, CSV building, and printing.
 *
 * NORMAL LEVELS ARE DEFINED HERE, ONCE. The Reports page shows each reading
 * beside the range it is expected to sit in, and that same table is what the CSV
 * and the printed report carry. Deriving it from the backend's accepted bounds
 * would have been wrong: `FEATURE_BOUNDS` in the API is the range a value is
 * physically ALLOWED to take (pH 0-14), not the range that is healthy. Those are
 * different numbers and conflating them would label pH 1 as "within range".
 *
 * These are the standard drinking-water reference values, and they are stated
 * here as reference rather than as a verdict — the verdict comes from the model.
 */

import { parseServerTime, waterSourceLabel } from '@/utils/format'

/**
 * Report modules stay free of UI helpers, so this is the one shared wording
 * function reused from `@/utils/format`. It is a pure string builder, so there is
 * no React or page dependency introduced.
 */
function waterSourceText(row) {
  return waterSourceLabel(row)
}

/** Per-parameter healthy reference bands, with the legal/typical limit for context. */
export const NORMAL_LEVELS = {
  ph: {
    label: 'pH',
    // Short symbol, used where the full label will not fit. Kept next to the
    // label rather than derived from it, so the table and the chat answers agree
    // on exactly what a parameter is called in a cramped column.
    symbol: 'pH',
    unit: 'pH',
    healthyLow: 6.5,
    healthyHigh: 8.5,
    note: 'Below 6.5 is corrosive; above 8.5 tastes flat and scales pipework.',
  },
  turbidity: {
    label: 'Turbidity',
    symbol: 'Turb',
    unit: 'NTU',
    healthyLow: 0,
    healthyHigh: 5,
    note: 'Cloudiness shelters bacteria from disinfection. The usual target is under 5 NTU.',
  },
  tds: {
    label: 'Total Dissolved Solids',
    symbol: 'TDS',
    unit: 'mg/L',
    healthyLow: 0,
    healthyHigh: 500,
    note: 'Dissolved salts and minerals. Above 500 mg/L the taste degrades and the source is suspect.',
  },
  temperature: {
    label: 'Temperature',
    symbol: 'Temp',
    unit: '°C',
    healthyLow: 10,
    healthyHigh: 25,
    note: 'Warm water holds less oxygen and grows bacteria faster.',
  },
  dissolved_oxygen: {
    label: 'Dissolved Oxygen',
    symbol: 'DO',
    unit: 'mg/L',
    healthyLow: 6.5,
    healthyHigh: 9.5,
    note: 'Low readings point to stagnant or heavily loaded water.',
  },
}

/**
 * The PHYSICAL range each parameter can take, i.e. what the API will accept.
 *
 * This is deliberately NOT the healthy band: pH is physically 0-14 but healthy
 * between 6.5 and 8.5. The report prints both, because "pH 5.2 is low" only
 * becomes actionable once the reader can see how low the scale actually goes.
 *
 * Kept here rather than imported from the backend constants so this module stays
 * free of an API dependency — it is imported by the PDF builder, which runs in a
 * plain browser context.
 */
export const FEATURE_BOUNDS = {
  ph: [0, 14],
  turbidity: [0, 1000],
  tds: [0, 5000],
  temperature: [0, 60],
  dissolved_oxygen: [0, 20],
}

/** Where a reading sits relative to its healthy band. */
export function classifyReading(key, value) {
  const band = NORMAL_LEVELS[key]
  if (!band || value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'unknown'
  }
  const number = Number(value)
  if (number < band.healthyLow) return 'low'
  if (number > band.healthyHigh) return 'high'
  return 'normal'
}

/** Human-readable wording for a classification. */
export const READING_WORDS = {
  low: 'Below normal',
  normal: 'Within normal',
  high: 'Above normal',
  unknown: 'Not recorded',
}

/**
 * The short form of each classification, for the compact mobile status column.
 *
 * SEPARATE FROM `READING_WORDS`, deliberately. Those strings are the ones the
 * CSV and PDF carry, where there is room for the full wording and where a
 * truncated "Above" would read as an unfinished sentence in an exported file.
 * The mobile table is a different problem: it has four columns in a ~350px card,
 * and "Above normal" there wrapped to two lines and made its row taller than its
 * neighbours. These one-word forms keep every row the same height. Keyed
 * identically, so a caller can switch between the two without a lookup table.
 */
export const READING_WORDS_SHORT = {
  low: 'Below',
  normal: 'In range',
  high: 'Above',
  unknown: 'Unknown',
}

/** The reference band as a display string, e.g. "6.5 – 8.5". */
export function normalRangeText(key) {
  const band = NORMAL_LEVELS[key]
  if (!band) return '—'
  return `${band.healthyLow} – ${band.healthyHigh}`
}

/**
 * A stable, human-quotable identifier for a stored prediction.
 *
 * Derived from the row's own id and timestamp, so it needs no extra column and
 * cannot drift from the record it names. Quoting it in a support message is
 * enough to find the exact row.
 */
export function reportId(row) {
  if (!row?.id) return '—'
  const stamp = String(row.created_at || '').replace(/\D/g, '').slice(0, 8) || '00000'
  return `AGR-${stamp}-${String(row.id).padStart(5, '0')}`
}

/** The prediction id, shown alongside the report id. */
export function predictionId(row) {
  return row?.id != null ? `PRED-${String(row.id).padStart(5, '0')}` : '—'
}

/** Escape one CSV field per RFC 4180: quote it when it contains a comma, quote or newline. */
function csvField(value) {
  const text = value === null || value === undefined ? '' : String(value)
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

/**
 * Build a CSV document from a header row plus data rows.
 *
 * A BOM is prepended deliberately. Excel on Windows reads a UTF-8 file as ANSI
 * without one, which turns the degree sign in "°C" into mojibake — and this
 * project's units use it on every temperature column.
 */
export function buildCsv(headers, rows) {
  const lines = [headers.map(csvField).join(',')]
  rows.forEach((row) => lines.push(row.map(csvField).join(',')))
  return `\uFEFF${lines.join('\r\n')}\r\n`
}

/** Trigger a client-side download of a text document. */
export function downloadText(filename, text, mime = 'text/csv;charset=utf-8') {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  // Revoked on the next tick: revoking synchronously can cancel the download in
  // some browsers before it has read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** A filename-safe timestamp, so two exports in the same minute do not collide. */
export function exportStamp(date = new Date()) {
  return date.toISOString().replace(/[:.]/g, '-').slice(0, 19)
}

/** The five parameter keys, in the order the table and the CSV present them. */
export const PARAMETER_ORDER = [
  'ph',
  'turbidity',
  'tds',
  'temperature',
  'dissolved_oxygen',
]

/**
 * One report as a CSV row, plus the header row it belongs to.
 *
 * Declared once and exported as a pair so a SINGLE report download, a bulk
 * download and the on-screen table all describe a reading with the same columns.
 * Building the headers inside the page (as it used to) meant a per-row export
 * had no headers of its own to reuse and would have drifted the moment a column
 * was added.
 *
 * It lives BELOW `PARAMETER_ORDER` on purpose: the header list is evaluated at
 * module load, so a const declared above the array it reads would hit the
 * temporal dead zone and throw before the app could start.
 */
export const reportCsv = {
  headers: [
    'Report ID',
    'Prediction ID',
    'Date',
    'Time',
    'Location',
    'Area',
    'City / Town',
    'Pincode',
    'District',
    'State',
    'Country',
    'Water Source',
    'Verdict',
    'Risk',
    'Confidence (%)',
    ...PARAMETER_ORDER.flatMap((key) => [
      `${NORMAL_LEVELS[key].label} (${NORMAL_LEVELS[key].unit})`,
      `${NORMAL_LEVELS[key].label} — normal range`,
      `${NORMAL_LEVELS[key].label} — status`,
    ]),
  ],
  row: (row) => [
    reportId(row),
    predictionId(row),
    // Formatted without the page's `formatDate` import so this module stays free
    // of a UI dependency; ISO slices give the same date/time split a report
    // needs and sort correctly in a spreadsheet.
    String(row?.created_at || '').slice(0, 10),
    String(row?.created_at || '').slice(11, 19),
    reportLocation(row),
    row?.location_area || 'Not Available',
    row?.location_city || 'Not Available',
    // The exact stored pincode when there is one; "Not Available" when not.
    row?.location_pincode ? String(row.location_pincode) : 'Not Available',
    row?.location_district || 'Not Available',
    row?.location_state || 'Not Available',
    row?.location_country || 'Not Available',
    // PROMPT 4: the same shared wording as the screen — the identified type, the
    // nearest real nearby source with its distance, or an explicit "unavailable".
    // Never a blank cell that could be read as "no source exists".
    waterSourceText(row),
    String(row?.prediction || '').toUpperCase(),
    ({ SAFE: 'Low', MODERATE: 'Medium', UNSAFE: 'High' }[
      String(row?.prediction || '').toUpperCase()
    ]) || 'Not Available',
    row?.confidence == null ? '' : (Number(row.confidence) * 100).toFixed(1),
    ...PARAMETER_ORDER.flatMap((key) => [
      row?.[key] ?? '',
      normalRangeText(key),
      READING_WORDS[classifyReading(key, row?.[key])],
    ]),
  ],
}

/**
 * The place a report was taken, as one string, or an empty string when the
 * prediction carried no location. Shared by the on-screen sheet, the CSV and the
 * PDF so all three name the location identically.
 */
export function reportLocation(row) {
  if (!row) return ''
  const parts = [
    row.location_name || row.location_city,
    row.location_state,
    row.location_country,
  ].filter(Boolean)
  return parts.join(', ')
}

/**
 * The report's pincode as display text. Read ONLY from the stored column: an
 * unset pincode becomes the brief's "Not Available" wording, never a value
 * inferred from the place or state.
 */
export function reportPincode(row) {
  return row?.location_pincode ? String(row.location_pincode) : 'Not Available'
}

/* ---------------------------------------------------------------------------
   PDF generation
   ---------------------------------------------------------------------------
   A REAL PDF FILE, built in the browser with jsPDF, rather than the print
   dialogue.

   WHY THIS REPLACED `window.print()`. Printing relies on the user knowing to
   choose "Save as PDF" in a dialog that looks nothing like a download, and the
   output depends on the browser's own pagination and on the print stylesheet.
   The requirement here is a DOWNLOAD — one report, or every reading at once —
   so the file is assembled explicitly: the page opens on the report title, the
   header carries the date/time and the document name, and the watermark and the
   grey rules the print stylesheet used to add are simply not drawn.

   The layout is deliberately formal: a CENTERED masthead with the drop-in-circle
   mark above the wordmark, equal left/right margins, every detail block set as
   a two-column label/value table so labels and values align in columns rather
   than drifting, and a very light circular water-drop watermark behind the
   content of every page (see `drawWatermark` for why it is painted last).
   --------------------------------------------------------------------------- */

/**
 * The water drop, as a SINGLE closed bezier silhouette centred on (cx, cy).
 *
 * The earlier version assembled the drop from jsPDF's ellipse + triangle
 * primitives, and the zoom render showed why that cannot work: two independent
 * strokes crossing each other read as "a circle with a triangle on it", not as
 * a drop. A drop is one continuous curve — pointed at the top, round at the
 * bottom — so it is drawn here as three bezier segments through the same six
 * anchor geometry, which keeps it a vector path (requirement 11) that reads
 * correctly at every size.
 */
function drawDrop(doc, cx, cy, diameter, style = 'F') {
  // Anchor geometry, in fractions of the mark's diameter:
  //   apex (0, -0.30) — the point of the drop
  //   right shoulder (0.27, 0.10), left shoulder (-0.27, 0.10)
  //   the shoulders connect through a deep bottom arc (controls at ±0.30, 0.42)
  //   that gives the drop its round belly.
  doc.lines(
    [
      // apex -> right shoulder
      [0.03, 0.20, 0.25, 0.28, 0.27, 0.4],
      // right shoulder -> left shoulder, through the bottom arc
      [0.03, 0.32, -0.57, 0.32, -0.54, 0],
      // left shoulder -> apex
      [0.02, -0.12, 0.3, -0.2, 0.27, -0.4],
    ],
    cx,
    cy - diameter * 0.3,
    [diameter, diameter],
    style,
    true,
  )
}

/**
 * The AquaGuard mark: a water drop enclosed in a circle (requirement 8).
 *
 * `size` is the diameter of the enclosing circle; the drop inside is scaled
 * from it so the two can never drift apart.
 */
function drawDropLogo(doc, cx, cy, diameter) {
  const r = diameter / 2
  doc.setDrawColor(2, 132, 199)
  doc.setLineWidth(diameter * 0.055)
  doc.circle(cx, cy, r, 'S')
  doc.setFillColor(14, 165, 233)
  drawDrop(doc, cx, cy, diameter * 0.78, 'F')
  doc.setLineWidth(0.2)
}

/**
 * THE WATERMARK (requirements 9-12).
 *
 * A large drop-in-circle, centred on the page. Painted as VECTOR geometry —
 * the same primitives as the logo — so it cannot pixelate at any zoom or
 * print resolution.
 *
 * WHY LIGHT COLOURS RATHER THAN OPACITY. The first cut drew full-saturation
 * strokes under an Ext-GState at 5% opacity. Several renderers — and print
 * pipelines — ignore or flatten the GState, and then the mark prints as a bold
 * blue shape sitting ON the text, the opposite of requirement 10. A hard-coded
 * pale colour needs no renderer support at all: on white paper it can only
 * ever read as a faint tint, at every zoom, in every viewer and on paper.
 */
function drawWatermark(doc) {
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const cx = pageWidth / 2
  const cy = pageHeight / 2
  const diameter = 105 // mm — large, but well inside the 210x297 page.

  // A FILLED SEAL, not an outline. The brief asks for a visible graphical
  // watermark that stays readable behind text, so the palest tints of the
  // brand blues are FILLED in — on white paper they can only read as a faint
  // tint, while the dark body text over them keeps full contrast. No
  // transparency API is involved, so the mark is identical in every viewer
  // and on paper. The double ring is what makes it read as a SEAL.
  doc.setFillColor(240, 249, 255) // the palest sky tint — the disc of the seal
  doc.setDrawColor(186, 230, 253)
  doc.setLineWidth(1.0)
  doc.circle(cx, cy, diameter / 2, 'FD')
  // The inner hairline ring — the second circle of the seal.
  doc.setDrawColor(191, 219, 254)
  doc.setLineWidth(0.6)
  doc.circle(cx, cy, diameter / 2 - 4, 'S')
  // The drop inside, filled one tint up so it reads as a solid water drop.
  doc.setFillColor(224, 242, 254)
  doc.setDrawColor(186, 230, 253)
  doc.setLineWidth(0.8)
  drawDrop(doc, cx, cy, diameter * 0.74, 'FD')
}

/** A coloured heading bar with white text, used for each section. */
function sectionBar(doc, text, y) {
  const pageWidth = doc.internal.pageSize.getWidth()
  const margin = 14
  doc.setFillColor(1, 99, 160)
  doc.rect(margin, y, pageWidth - margin * 2, 7, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9.5)
  doc.setTextColor(255, 255, 255)
  // CENTERED: the section title sits on the middle of its own bar, matching
  // the centered masthead and the centered tables, so the whole document
  // reads as one designed layout rather than mixed alignments.
  doc.text(text, pageWidth / 2, y + 4.9, { align: 'center' })
  doc.setTextColor(30, 41, 59)
  return y + 10
}

/**
 * Start a fresh page when the remaining space cannot hold a section.
 *
 * REQUIREMENT 6. Each of the report's blocks is 30–70mm tall, so a block that
 * starts near the bottom spills across the page break and its section bar ends
 * up orphaned above the footer. `ensureSpace` is called BEFORE each block with
 * that block's rough height: below the threshold it breaks first, so a section
 * always begins at the top of a page it can finish on.
 */
function ensureSpace(doc, y, needed) {
  const pageHeight = doc.internal.pageSize.getHeight()
  const bottom = pageHeight - 20 // footer zone
  if (y + needed > bottom) {
    doc.addPage()
    return 20 // top content line on the fresh page
  }
  return y
}

/**
 * The masthead, shared by the single and bulk exports.
 *
 * EVERYTHING IS CENTRED (requirement 2): the drop-in-circle mark, the wordmark,
 * the project line, the document title and the generation timestamp all sit on
 * the page's vertical axis, with the hairline below spanning exactly the
 * content width so the margins stay equal on both sides.
 */
function drawMasthead(doc, { title }) {
  const pageWidth = doc.internal.pageSize.getWidth()
  const margin = 14
  const cx = pageWidth / 2

  drawDropLogo(doc, cx, 20, 16)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(17)
  doc.setTextColor(15, 23, 42)
  doc.text('AquaGuard AI', cx, 34, { align: 'center' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(100, 116, 139)
  doc.text('Water Quality Monitoring & Prediction', cx, 39.5, { align: 'center' })

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(30, 58, 96)
  doc.text(title || 'Screening report', cx, 48, { align: 'center' })

  const now = new Date()
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(100, 116, 139)
  doc.text(`Generated ${now.toLocaleDateString()} at ${now.toLocaleTimeString()}`, cx, 53.5, {
    align: 'center',
  })

  // A single hairline under the masthead, spanning the content width only, so
  // it ends exactly at both margins.
  doc.setDrawColor(203, 213, 225)
  doc.setLineWidth(0.2)
  doc.line(margin, 58, pageWidth - margin, 58)

  return 64
}

/**
 * What the numbers mean, per parameter, as PDF table rows.
 *
 * Two bands are printed for each parameter, and they are DIFFERENT things:
 *
 *   NORMAL      the healthy drinking-water band (NORMAL_LEVELS.healthyLow/High)
 *   ABNORMAL    everything a valid reading can be OUTSIDE that band, expressed
 *               against the physical limits the model accepts. This is what the
 *               user needs in order to judge a bad number: knowing pH 5.2 is
 *               "low" is not actionable without knowing how low is possible.
 */
function parameterRows(row) {
  return PARAMETER_ORDER.map((key) => {
    const band = NORMAL_LEVELS[key]
    const bounds = FEATURE_BOUNDS[key]
    const status = classifyReading(key, row?.[key])
    return [
      `${band.label}\n(${band.unit})`,
      `${formatCell(row?.[key])} ${band.unit}`,
      `${normalRangeText(key)} ${band.unit}`,
      bounds ? `below ${bounds[0]} or above ${bounds[1]} ${band.unit}` : '—',
      READING_WORDS[status],
    ]
  })
}

/**
 * The steps to take, chosen by the report's verdict.
 *
 * These are the ACTIONS attached to each verdict — the user asked for the
 * instructions to sit under the result, and a verdict without a next step is
 * the part of a report people ignore. They are static text keyed off the
 * verdict, not a second opinion from anywhere.
 */
export const VERDICT_STEPS = {
  safe: [
    'This sample is within the healthy band for every parameter measured. The water is treated as potable at the point of testing.',
    'Store it in a clean, covered container and use it within 24 hours of sampling.',
    'Retest on your normal schedule. A single clean reading describes one moment, not the supply.',
  ],
  moderate: [
    'At least one reading sits between the clean and unsafe bands, so the result is a flag rather than a pass.',
    'Do not drink this water untreated. Boil it for at least one minute, or use bottled water, until a retest comes back clean.',
    'Find and correct the parameter marked Below/Above normal in the table above, then sample again from the same tap.',
  ],
  unsafe: [
    'Treat this water as contaminated. Do not drink it, cook with it, or use it to brush teeth while untreated.',
    'Boil for at least one minute, or use bottled water, and keep the source isolated until it is cleared.',
    'Retest from the same point. If the second result is also unsafe, have a laboratory analysis done before using the supply again.',
  ],
}

/** General instructions that apply to every report, printed under the steps. */
export const GENERAL_INSTRUCTIONS = [
  'Sample from the same tap or source each time, and record the time of sampling. Readings taken at different points are not comparable.',
  'Clean the container before sampling and let the water run briefly first, so the sample is what the supply is actually delivering.',
  'The normal ranges printed here are the standard drinking-water reference bands, shown for comparison only. The verdict itself comes from the model, not from these bands.',
  'Confidence is the model\u2019s strength of opinion about this sample. A low figure means some parameters were left out \u2014 not that the water is uncertain.',
  'This report is a screening result from five measured parameters and a statistical model. It is not a laboratory analysis and must not be treated as one.',
]

/**
 * One reading as a PDF file, or many readings as one multi-section PDF.
 *
 * `rows` is a list of the same row shape the page already works with, so a
 * single-report download and a bulk download share every line of this function.
 */
export async function downloadReportsPdf(rows, { filename, title, output } = {}) {
  const list = Array.isArray(rows) ? rows.filter(Boolean) : []
  if (list.length === 0) return

  // Loaded on demand: jsPDF is a few hundred KB, and the Reports page should not
  // pay for it until the user actually asks for a PDF.
  // `vite-ignore` on the specifier keeps the dev server's pre-bundler and
  // Rollup from statically following these imports at build time. jsPDF's own
  // bundle contains a guarded `import('canvg')` for an SVG feature this app
  // never calls; a static analysis of the whole graph chokes on the missing
  // optional package, whereas a runtime import resolves only what is actually
  // on disk and lets jsPDF's own try/catch handle the rest.
  const [jspdfModule, autoTableModule] = await Promise.all([
    import(/* @vite-ignore */ 'jspdf'),
    import(/* @vite-ignore */ 'jspdf-autotable'),
  ])
  const jsPDF = jspdfModule.jsPDF || jspdfModule.default
  // jspdf-autotable's export shape varies with how the bundler wraps the CJS
  // module: sometimes the plugin function is the module itself, sometimes it is
  // `.default`, and under Vite it is `.default.default` (a CJS module whose own
  // default export is the function). The first FUNCTION found in that chain is
  // the one to call, so this walks the candidates rather than assuming a shape.
  const autoTable =
    [autoTableModule, autoTableModule.default, autoTableModule.default?.default]
      .find((candidate) => typeof candidate === 'function') ||
    // Last resort: the older API registered itself as `doc.autoTable`. Bind it
    // so the call signature below (`autoTable(doc, options)`) still works.
    ((docInstance, options) => docInstance.autoTable(options))

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const margin = 14
  let y = drawMasthead(doc, {
    title: title || `${list.length} reading${list.length === 1 ? '' : 's'}`,
  })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const contentWidth = pageWidth - margin * 2
  list.forEach((row, index) => {
    if (index > 0) {
      doc.addPage()
      y = drawMasthead(doc, { title: `Reading ${index + 1} of ${list.length}` })
    }

    y = ensureSpace(doc, y, 75)
    y = sectionBar(doc, 'REPORT DETAILS', y)

    // --- Identity block as a label/value table -----------------------------
    // Rather than free-floating text lines (which drift as label lengths
    // change), every detail is a row in an autoTable with a fixed label column:
    // labels right up against a consistent gutter, values starting at exactly
    // the same x on every row (requirement 4).
    const created = row?.created_at ? parseServerTime(row.created_at) : null
    const when = created && !Number.isNaN(created.getTime())
      ? // IST, matching every screen: the report's own timestamp must agree
        // with what History showed the user when they saved it.
        `${new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata', hour12: true }).format(created)}`
      : 'Not Available'
    const verdict = String(row?.prediction || '').toUpperCase()
    // The plain-word risk level — a reading of the model's own verdict, never a
    // second score. Same wording History and the detail panel use.
    const risk = { SAFE: 'Low', MODERATE: 'Medium', UNSAFE: 'High' }[verdict] || 'Not available'
    const detailRows = [
      ['Report ID', reportId(row)],
      ['Prediction ID', predictionId(row)],
      ['Date and time', when],
      ['Location', reportLocation(row) || 'Not Available'],
      ['Area', row?.location_area || 'Not Available'],
      ['City / Town', row?.location_city || 'Not Available'],
      ['District', row?.location_district || 'Not Available'],
      ['State', row?.location_state || 'Not Available'],
      ['Country', row?.location_country || 'Not Available'],
      ['Pincode', row?.location_pincode ? String(row.location_pincode) : 'Not Available'],
      ['Water source', waterSourceText(row)],
      ['Model version', row?.model_version || row?.modelVersion || 'Not Available'],
    ]
    autoTable(doc, {
      startY: y,
      margin: { left: margin, right: margin },
      body: detailRows,
      theme: 'plain',
      styles: {
        fontSize: 9,
        cellPadding: { top: 1.2, bottom: 1.2, left: 0, right: 2 },
        textColor: [30, 41, 59],
        // CENTERED, per the layout requirement: the identity block (Report ID,
        // Prediction ID, date, location and the rest) reads centered across the
        // full content width, rather than ragged-left under the section bar.
        halign: 'center',
      },
      columnStyles: {
        0: { cellWidth: 32, fontStyle: 'bold', textColor: [71, 85, 105] },
        1: { cellWidth: 'auto' },
      },
    })
    y = (doc.lastAutoTable?.finalY ?? y) + 5
    // --- Verdict banner ---------------------------------------------------
    // A colour-coded band keyed to the verdict, so the single most important
    // fact in the document is also the most visible one.
    const VERDICT_RGB = {
      SAFE: [22, 163, 74],
      MODERATE: [217, 119, 6],
      UNSAFE: [220, 38, 38],
    }
    const tone = VERDICT_RGB[verdict] || [100, 116, 139]
    doc.setFillColor(tone[0], tone[1], tone[2])
    doc.rect(margin, y, contentWidth, 9, 'F')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(255, 255, 255)
    // CENTERED BANNER: verdict and confidence on one centered line, so the
    // single most important fact in the document sits on the middle of the
    // band the way the masthead does.
    doc.text(
      `Overall verdict: ${verdict || 'Not Available'}   —   Risk: ${risk}   —   Confidence: ${
        row?.confidence == null ? 'Not Available' : `${(Number(row.confidence) * 100).toFixed(1)}%`
      }`,
      pageWidth / 2,
      y + 6.2,
      { align: 'center' },
    )
    doc.setTextColor(30, 41, 59)
    y += 14
    y = ensureSpace(doc, y, 70)
    // --- Parameter table, with BOTH bands ---------------------------------
    // `showHead: 'everyPage'` is the autoTable default, spelled out here because
    // it IS requirement 6: when the table flows onto a second page the header
    // row is drawn again, so a reader never meets orphaned data rows.
    autoTable(doc, {
      startY: y,
      margin: { left: margin, right: margin, top: 20 },
      head: [['Parameter', 'Measured', 'Normal range', 'Abnormal range', 'Status']],
      body: parameterRows(row),
      styles: {
        fontSize: 8.5,
        cellPadding: 2.4,
        textColor: [30, 41, 59],
        valign: 'middle',
        // CENTERED COLUMNS: every cell in the parameter table is centered in its
        // column, so the numbers line up under their headings down the page.
        halign: 'center',
      },
      headStyles: {
        fillColor: [1, 99, 160],
        textColor: [255, 255, 255],
        fontStyle: 'bold',
        fontSize: 8.5,
        // CENTERED HEADINGS: the header labels sit over the centered columns
        // rather than breaking the alignment with a left-leaning label row.
        halign: 'center',
      },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      columnStyles: {
        0: { cellWidth: 30 },
        1: { cellWidth: 26, fontStyle: 'bold' },
        2: { cellWidth: 30 },
        3: { cellWidth: contentWidth - 30 - 26 - 30 - 26 },
        4: { cellWidth: 26 },
      },
      theme: 'grid',
    })
    y = (doc.lastAutoTable?.finalY ?? y) + 8
    y = ensureSpace(doc, y, 65)
    // --- Steps to take, keyed to the verdict ------------------------------
    y = sectionBar(doc, 'WHAT TO DO NEXT', y)
    doc.setFontSize(8.5)
    const steps = VERDICT_STEPS[String(row?.prediction)] || VERDICT_STEPS.safe
    steps.forEach((line, stepIndex) => {
      const wrapped = doc.splitTextToSize(`${stepIndex + 1}.  ${line}`, contentWidth - 2)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(51, 65, 85)
      doc.text(wrapped, margin + 1, y + 1)
      y += wrapped.length * 4.4 + 2.2
    })
    y += 3
    y = ensureSpace(doc, y, 60)
    // --- Per-parameter meaning, so the sheet explains its own numbers ------
    y = sectionBar(doc, 'WHAT EACH PARAMETER MEANS', y)
    doc.setFontSize(8)
    PARAMETER_ORDER.forEach((key) => {
      const band = NORMAL_LEVELS[key]
      const wrapped = doc.splitTextToSize(
        `${band.label} (${band.unit}):  ${band.note}`,
        contentWidth - 2,
      )
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(100, 116, 139)
      doc.text(wrapped, margin + 1, y + 1)
      y += wrapped.length * 4 + 1.6
    })
    y += 3
    y = ensureSpace(doc, y, 55)
    // --- Reading and sampling notes -------------------------------------
    y = sectionBar(doc, 'READING AND SAMPLING NOTES', y)
    doc.setFontSize(8)
    GENERAL_INSTRUCTIONS.forEach((line) => {
      const wrapped = doc.splitTextToSize(`-  ${line}`, contentWidth - 2)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(100, 116, 139)
      doc.text(wrapped, margin + 1, y + 1)
      y += wrapped.length * 4 + 1.8
    })

    // --- The disclaimer (requirement 16) -----------------------------------
    // Set after the notes, before the watermark pass, in italic and set off by
    // a hairline so it reads as a formal notice rather than as one more bullet.
    y = ensureSpace(doc, y + 2, 20)
    doc.setDrawColor(203, 213, 225)
    doc.setLineWidth(0.2)
    doc.line(margin, y, pageWidth - margin, y)
    y += 3
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(8)
    doc.setTextColor(100, 116, 139)
    const disclaimer = doc.splitTextToSize(
      'Disclaimer: This report is generated by an AI-based screening model. It is not certified laboratory testing and must not be used as the sole basis for decisions about drinking-water safety.',
      contentWidth,
    )
    doc.text(disclaimer, margin, y + 2)
    y += disclaimer.length * 4 + 3
    doc.setFont('helvetica', 'normal')
  })

  // THE WATERMARK PASS. Runs after all content on every page (including pages
  // autoTable created itself), so the mark cannot be overpainted, and its
  // outline-only drawing keeps everything underneath readable. See
  // `drawWatermark`.
  const pageCount = doc.getNumberOfPages()
  for (let p = 1; p <= pageCount; p += 1) {
    doc.setPage(p)
    drawWatermark(doc)
    // The footer is drawn here too, per page, centred (requirements 2, 5, 6):
    // one identifying line for every page of the document, including pages a
    // long parameter table or a long reading list flowed onto.
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(148, 163, 184)
    doc.text(
      `AquaGuard AI screening report  |  ${list.length} reading${list.length === 1 ? '' : 's'}  |  page ${p} of ${pageCount}`,
      pageWidth / 2,
      pageHeight - 8,
      { align: 'center' },
    )
  }
  doc.setTextColor(30, 41, 59)

  // DEFAULT BEHAVIOUR IS UNCHANGED: save the file to disk. The options popup's
  // "attachment preparation" passes output:'blob' instead, and gets the exact
  // same PDF as an in-memory Blob — no download is triggered and no byte of the
  // document differs, so an attachment and a saved file can never disagree.
  if (output === 'blob') {
    return doc.output('blob')
  }
  doc.save(filename || `aquaguard-report-${exportStamp()}.pdf`)
}

/** A number as it should read in a PDF cell. */
function formatCell(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return String(value)
  return Number.isInteger(number) ? String(number) : number.toFixed(2)
}
