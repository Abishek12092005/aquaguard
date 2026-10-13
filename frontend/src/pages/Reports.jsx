import { useMemo, useState } from 'react'

import { locationApi, predictionApi } from '@/api'
import Badge from '@/components/Badge'
import Button from '@/components/Button'
import Card from '@/components/Card'
import EmptyState from '@/components/EmptyState'
import ErrorState from '@/components/ErrorState'
import Icon from '@/components/Icon'
import PageHeader from '@/components/PageHeader'
import Spinner from '@/components/Spinner'
import { ICONS } from '@/config/navigation'
import { useApi } from '@/hooks/useApi'
import { REFRESH_GROUPS, useDataRefresh } from '@/utils/dataRefresh'
import { formatNumber, formatPercent, formatPredictionStamp, waterSourceLabel } from '@/utils/format'
import {
  GENERAL_INSTRUCTIONS,
  NORMAL_LEVELS,
  PARAMETER_ORDER,
  READING_WORDS,
  READING_WORDS_SHORT,
  VERDICT_STEPS,
  buildCsv,
  classifyReading,
  downloadText,
  exportStamp,
  normalRangeText,
  predictionId,
  reportId,
  reportCsv,
  reportLocation,
} from '@/utils/reports'

/**
 * Reports — a per-reading report with a full detail table, and two ways out.
 *
 * WHY THE "PDF" IS THE BROWSER'S PRINT DIALOGUE. Generating a real PDF file would
 * mean adding a PDF library (jsPDF/pdfmake, several hundred KB) plus its font
 * embedding, or a server-side renderer with a headless browser behind it. Since
 * every modern browser already produces a PDF from the print dialogue — with
 * proper page breaks, selectable text and embedded fonts — the honest choice is
 * to print rather than to ship a second, worse renderer. The button says
 * "Print / save as PDF" so the user knows what will happen, and a `@media print`
 * block in `index.css` strips the app chrome so the sheet is only the report.
 *
 * A CSV export sits beside it for the case print cannot serve: taking the numbers
 * into a spreadsheet.
 *
 * The VERDICT and its confidence come from the model. The normal-range column is
 * a printed reference band, not a second opinion — the page says so, because a
 * table that shows "pH 5.2 / normal 6.5-8.5 / UNSAFE" invites the reader to think
 * the ranges produced the verdict.
 */

/**
 * The FOUR export/action buttons in the header share one appearance.
 *
 * They sit beside each other, so a single class keeps them from drifting apart.
 *
 * BLACK WITH WHITE TEXT AT REST, BLUE WITH WHITE TEXT ON HOVER — in BOTH themes.
 * The light-mode default for a `Button` is the aqua primary, so the black fill is
 * stated for the light theme too rather than only under `dark:`. The hover blue is
 * the one colour that reads as "this is the control under the pointer" against a
 * black pill on either page background.
 */
const DL_BUTTON =
  'min-w-0 bg-black text-white px-2.5 py-1.5 text-2xs sm:px-3.5 sm:py-2 sm:text-sm hover:bg-aqua-500 hover:text-white active:bg-aqua-600 active:text-white dark:bg-black dark:text-white dark:hover:bg-aqua-500 dark:hover:text-white dark:active:bg-aqua-600 dark:active:text-white'

export default function Reports() {
  const [riskFilter, setRiskFilter] = useState(undefined)
  const [selectedId, setSelectedId] = useState(null)

  // --- Reports to Mail (UI only) ------------------------------------------
  // The button opens a small email-entry modal. NOTHING IS SENT: there is no
  // network call here, only local state and client-side validation. A valid
  // address is acknowledged; an invalid one gets a clear inline message.
  const [mailOpen, setMailOpen] = useState(false)
  const [mailEmail, setMailEmail] = useState('')
  const [mailError, setMailError] = useState('')
  const [mailAccepted, setMailAccepted] = useState(false)

  // --- STEP: the four export choices, shown after a valid email ---
  // `mailChoice` is the ONE option picked in the "Download Reports to Our
  // Mail" popup (radio behaviour: only one at a time, and Send stays DISABLED
  // until something is picked). `mailNote` carries the inline response to the
  // Send click — nothing is emailed in this step, so the note says so.
  const [mailChoice, setMailChoice] = useState(null)
  const [mailNote, setMailNote] = useState('')
  // A preparation FAILURE (PDF generation threw) is shown here — separate from
  // `mailNote` so an error and a success never overwrite each other.
  const [mailAttachError, setMailAttachError] = useState('')
  // IN-FLIGHT guard for the Send button. While true the button is disabled and
  // reads "Sending...", so a double click can never fire two API calls.
  const [mailSending, setMailSending] = useState(false)
  // THE SUCCESS PHASE, in two steps:
  //   `mailSent`      the backend CONFIRMED the send — the popup's body is
  //                   replaced by the single success line (options + Send are
  //                   gone). Never set on any failure; only the backend's
  //                   `status === "sent"` reaches it.
  //   `mailFading`    after the 2-second hold, the fade-out class is applied and
  //                   the popup unmounts when the transition ends.
  const [mailSent, setMailSent] = useState(false)
  const [mailFading, setMailFading] = useState(false)

  function openMailModal() {
    setMailEmail('')
    setMailError('')
    setMailAccepted(false)
    setMailChoice(null)
    setMailNote('')
    setMailAttachError('')
    setMailSending(false)
    setMailSent(false)
    setMailFading(false)
    setMailOpen(true)
  }

  function closeMailModal() {
    setMailOpen(false)
    setMailError('')
    setMailAccepted(false)
    setMailChoice(null)
    setMailNote('')
    setMailAttachError('')
    setMailSending(false)
    setMailSent(false)
    setMailFading(false)
  }

  /**
   * Validate the typed address client-side and record the verdict.
   *
   * The regex is deliberately simple and honest: `local@domain.tld`, where the
   * domain has at least one dot and no spaces. It is not the full RFC 5322
   * grammar — a full grammar accepts exotic addresses no mail provider issues —
   * and this check only decides whether the typed text LOOKS like an email
   * address, which is what this step asks for. No email is sent either way.
   */
  function submitMail(event) {
    event.preventDefault()
    const value = mailEmail.trim()
    const looksLikeEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
    if (!value) {
      setMailError('Please enter an email address.')
      setMailAccepted(false)
      return
    }
    if (!looksLikeEmail) {
      setMailError('Please enter a valid email address (e.g. name@example.com).')
      setMailAccepted(false)
      return
    }
    setMailError('')
    setMailAccepted(true)
  }

  /**
   * The Send click in the options popup — the REAL send.
   *
   * Calls `POST /api/v1/reports/mail`, which builds the attachment server-side
   * (from the authenticated user's OWN rows) and sends it through the shared
   * SMTP transport. The BACKEND RESPONSE decides what the user is told:
   *
   *   200  the provider accepted the message — and only then is success shown
   *   4xx  the request itself was wrong (option, id, address, ownership)
   *   5xx  the attachment could not be built, or the provider refused
   *
   * A failed send shows the backend's own message verbatim — the UI never
   * fabricates a success. The popup STAYS OPEN either way, so the note (or the
   * error) is visible in context and the user can correct and retry.
   */
  /**
   * PROMPT 12 — the device label for the audit row.
   *
   * Only what the user agent already tells everyone, paraphrased: the platform
   * and browser family. It is a convenience label, never a fingerprint.
   */
  function deviceLabel() {
    try {
      const ua = navigator.userAgent || ''
      const browser = /Edg\//.test(ua) ? 'Edge'
        : /OPR\//.test(ua) ? 'Opera'
        : /Chrome\//.test(ua) ? 'Chrome'
        : /Safari\//.test(ua) && /Version\//.test(ua) ? 'Safari'
        : /Firefox\//.test(ua) ? 'Firefox'
        : null
      const os = /Windows/.test(ua) ? 'Windows'
        : /Mac OS X/.test(ua) ? 'macOS'
        : /Android/.test(ua) ? 'Android'
        : /iPhone|iPad/.test(ua) ? 'iOS'
        : /Linux/.test(ua) ? 'Linux'
        : null
      return [os, browser].filter(Boolean).join(' · ') || null
    } catch {
      return null
    }
  }

  /**
   * PROMPT 12 — the consented device location, or null.
   *
   * THREE GUARDS, IN ORDER, and every failure returns null:
   *
   *   1. the browser must expose geolocation at all;
   *   2. the Permissions API must report the geolocation permission as
   *      GRANTED. If it is 'denied' there is no location; if it is 'prompt'
   *      the user has NOT yet granted it, so we do not raise a surprise
   *      permission dialog in the middle of sending a report — we simply do
   *      not collect. This is what makes the capture "explicit permission"
   *      rather than a sneaky ask;
   *   3. the reverse-geocode must succeed and return real place fields.
   *
   * Only the RESOLVED PLACE travels to the server (name/city/state/country/
   * pincode, tagged source:"browser"). The raw coordinates are discarded here
   * and are never sent or stored, which keeps the audit at place granularity
   * only — a browser-provided approximate location, clearly distinguishable
   * from a precise postal address.
   */
  async function collectConsentedDeviceLocation() {
    try {
      if (typeof navigator === 'undefined' || !('geolocation' in navigator)) return null
      // Check the permission state first — never a surprise prompt.
      let granted = false
      if (navigator.permissions?.query) {
        try {
          const status = await navigator.permissions.query({ name: 'geolocation' })
          granted = status?.state === 'granted'
        } catch {
          granted = false
        }
      }
      if (!granted) return null

      const position = await new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
          (pos) => resolve(pos),
          () => resolve(null),
          { enableHighAccuracy: false, timeout: 8000, maximumAge: 5 * 60 * 1000 },
        )
      })
      const { latitude, longitude } = position?.coords || {}
      if (typeof latitude !== 'number' || typeof longitude !== 'number') return null

      // One reverse-geocode of one fix; the coordinates go no further.
      const response = await locationApi.reverse({ lat: latitude, lon: longitude })
      const place = response?.data ?? response ?? {}
      const fields = {
        source: 'browser',
        name: place.name || null,
        city: place.city || null,
        state: place.state || null,
        country: place.country || null,
        pincode: place.pincode || null,
      }
      // A bare "browser" tag with no real place would be a claim the row
      // cannot back up — only send it if at least one field resolved.
      const hasAny = Object.entries(fields).some(([k, v]) => k !== 'source' && v)
      return hasAny ? fields : null
    } catch {
      // Any failure — permission, GPS, network, geocoder — degrades to the
      // same honest null. The audit row will read "Location unavailable".
      return null
    }
  }
  async function sendMailChoice(event) {
    event.preventDefault()
    // Duplicate-click guard: an in-flight send is not restarted, and the same
    // guard keeps the button disabled while the request runs.
    if (!mailChoice || mailSending) return

    const OPTION_CODES = {
      report_pdf: 'REPORT_PDF',
      report_csv: 'REPORT_CSV',
      all_pdf: 'ALL_PDF',
      all_csv: 'ALL_CSV',
    }
    const recipient = mailEmail.trim()
    const isSingle = mailChoice === 'report_pdf' || mailChoice === 'report_csv'
    const isAll = mailChoice === 'all_pdf' || mailChoice === 'all_csv'

    // --- Preflight guards: fail EARLY, in the popup, before any network call.
    // Each keeps the popup open and the chosen option intact, so the user can
    // fix the cause and press Send again. A guard failure is NEVER a success.
    if (!recipient) {
      setMailError('Please enter an email address.')
      setMailAccepted(false)
      return
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) {
      setMailError('Please enter a valid email address (e.g. name@example.com).')
      setMailAccepted(false)
      return
    }
    if (isSingle && !selected) {
      setMailAttachError('Please select a report first — this option attaches one specific report.')
      return
    }
    if (isAll && rows.length === 0) {
      setMailAttachError('You have no reports to send yet. Submit a water-quality prediction first.')
      return
    }

    setMailSending(true)
    setMailNote('')
    setMailAttachError('')
    try {
      // --- PROMPT 12: consent-gated device location for the audit trail ------
      // Collected ONLY here, at the moment of the send, and ONLY when the
      // browser already reports the geolocation permission as GRANTED. This
      // never raises a prompt of its own (a prompt mid-send would be a surprise
      // ask), and when the permission is denied, unavailable or merely
      // "prompt"-able, `device_location` is sent as null — the audit row then
      // reads "Location unavailable". No coordinates are ever sent: the fix is
      // reverse-geocoded and only the place NAME/CITY/STATE/COUNTRY/PINCODE
      // travel to the server, which refuses anything but source:"browser".
      const deviceLocation = await collectConsentedDeviceLocation()
      const response = await predictionApi.mailReports({
        email: recipient,
        option: OPTION_CODES[mailChoice],
        // Required by the backend ONLY for the single-report options; the ALL
        // options attach every report the account owns and reject a stray id.
        prediction_id: isSingle ? selected.id : undefined,
        // Audit fields. `device_location` is null when there is nothing
        // legitimately available — never a guessed place.
        device_location: deviceLocation,
        device_label: deviceLabel(),
      })

      // SUCCESS ONLY ON THE BACKEND'S WORD.
      //
      // The success envelope carries `sent: true` (see report_mail_routes.py),
      // NOT a `status` field. An earlier version of this checked
      // `response.data.status === 'sent'`, which can never be true - so a
      // genuinely delivered mail was reported to the user as a failure. Caught
      // by running the endpoint for real rather than by reading the code.
      if (response?.data?.sent === true) {
        // The four options and the Send button give way to the single success
        // line; the 2-second hold and the fade are scheduled below.
        setMailSent(true)
        const HOLD_MS = 2000
        const FADE_MS = 300
        window.setTimeout(() => setMailFading(true), HOLD_MS)
        window.setTimeout(closeMailModal, HOLD_MS + FADE_MS)
      } else {
        // The request went through but the send did not happen (provider
        // refused, attachment could not be built, mail disabled...). The
        // backend's own detail is shown verbatim; the option stays selected
        // and Send stays enabled for a retry.
        setMailAttachError(
          response?.data?.detail ||
            response?.message ||
            'The email could not be sent. Please try again.',
        )
      }
    } catch (err) {
      // The interceptor normalises every failure into `err.message` plus a
      // `status` and an `isNetworkError` flag. Distinguish the three families
      // the user experiences differently, and keep the POPUP OPEN and the
      // OPTION SELECTED in all of them so retry is one click away.
      if (err?.isNetworkError) {
        setMailAttachError(
          'Cannot reach the AquaGuard AI server. Check your connection and try again.',
        )
      } else if (err?.status === 404) {
        setMailAttachError(
          'That report could not be found in the stored records. It may have been deleted — reselect it and try again.',
        )
      } else if (err?.status === 422) {
        setMailAttachError(
          err?.message || 'The send request was not valid. Please re-check the address and option, then retry.',
        )
      } else if (err?.status === 502) {
        // Provider refusal or attachment-generation failure — the backend's
        // message already says which.
        setMailAttachError(err?.message || 'The email could not be sent. Please try again.')
      } else if (err?.status === 503) {
        setMailAttachError(
          'Email sending is not available right now. Please try again later.',
        )
      } else {
        setMailAttachError(err?.message || 'The email could not be sent. Please try again.')
      }
    } finally {
      setMailSending(false)
    }
  }

  // One page of history is plenty for a report view; the full record set is on
  // the History screen, which is built for scanning.
  const history = useApi(() => predictionApi.history({ per_page: 100 }), [])

  // THE FILTER-CHIP COUNTS, COUNTED IN THE DATABASE FROM REAL RECORDS.
  //
  // These are NOT tallied from `rows`. The list above is deliberately bounded
  // (`per_page: 100`), so a browser-side tally would show a capped total for any
  // account with more readings, and would silently disagree with the data. The
  // server groups and counts the caller's OWN rows in SQL and returns the four
  // figures, so `all === safe + moderate + unsafe` always holds.
  const counts = useApi(() => predictionApi.counts(), [])

  useDataRefresh(REFRESH_GROUPS.dashboard, () => {
    history.refetch()
    counts.refetch()
  })

  // Memoised so the array identity is stable between renders. Without this the
  // `|| []` fallback produced a NEW array on every render, which invalidated the
  // `filtered` memo below on every render too — the memo was doing nothing.
  const rows = useMemo(() => history.data?.data || [], [history.data])

  const filtered = useMemo(
    () => (riskFilter ? rows.filter((row) => row.prediction === riskFilter) : rows),
    [rows, riskFilter],
  )

  // Default to the newest row so the page is useful on arrival rather than
  // asking for a selection before it will show anything.
  const selected =
    filtered.find((row) => row.id === selectedId) || filtered[0] || null

  /**
   * Download EVERYTHING currently on screen as one CSV.
   *
   * The export follows the ON-SCREEN filter, so "download all" always means
   * "download what I am looking at" rather than everything the account holds.
   * The per-row CSV builder lives in `@/utils/reports` (`reportCsv`) so a single
   * report and a bulk export share one column layout — the two can never
   * disagree about what a report contains.
   */
  function exportAllCsv() {
    const scope = riskFilter ? riskFilter : 'all'
    downloadText(
      `aquaguard-reports-${scope}-${exportStamp()}.csv`,
      buildCsv(reportCsv.headers, filtered.map(reportCsv.row)),
    )
  }

  /** Download exactly ONE report as CSV, without touching the list selection. */
  function exportOneCsv(row) {
    downloadText(
      `aquaguard-report-${reportId(row)}-${exportStamp()}.csv`,
      buildCsv(reportCsv.headers, [reportCsv.row(row)]),
    )
  }

  /**
   * Download EVERYTHING currently on screen as one PDF.
   *
   * THE ONE-GENERATOR RULE, APPLIED TO THE BULK EXPORT TOO. This asks the SERVER
   * for the document, built by the same `build_pdf` the email attachment and the
   * single-report download use. The page no longer re-derives its own PDF in the
   * browser: a second builder was a second layout, a second timestamp path and a
   * second watermark that could drift from the emailed report.
   *
   * The server scopes the document to the caller's own rows, in the same
   * newest-first order the list shows.
   */
  async function exportAllPdf() {
    try {
      const response = await predictionApi.downloadAllReportsPdf()
      const blob = response?.data || response
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `aquaguard-reports-all-${exportStamp()}.pdf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (err) {
      window.alert(
        err?.message || 'The reports could not be generated. Please try again.',
      )
    }
  }

  /**
   * Download ONE report as a PDF.
   *
   * THE ONE-GENERATOR RULE: this asks the SERVER for the PDF, built by the same
   * `build_pdf` the email attachment uses. A downloaded report and an emailed
   * one are therefore byte-for-byte the same layout, the same stored timestamp
   * and the same watermark — the browser-side jsPDF builder was a second
   * implementation that could drift, so the per-report download no longer runs
   * through it. `downloadBlob` names the file from the server's own id.
   */
  async function exportOnePdf(row) {
    if (!row) return
    try {
      const response = await predictionApi.downloadReportPdf(row.id)
      const blob = response?.data || response
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `aquaguard-report-${reportId(row)}.pdf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (err) {
      // A failed generation is reported, never swallowed into silence: the user
      // must know the download did not happen rather than wonder where it went.
      window.alert(
        err?.message || 'The report could not be generated. Please try again.',
      )
    }
  }

  // Counts come from the server's own group-by of the caller's rows. While they
  // are in flight the chips read 0 rather than a stale or invented figure.
  const summary = counts.data?.data || {}
  const tiles = [
    { key: undefined, label: 'All readings', value: summary.all ?? 0 },
    { key: 'safe', label: 'Safe', value: summary.safe ?? 0 },
    { key: 'moderate', label: 'Moderate', value: summary.moderate ?? 0 },
    { key: 'unsafe', label: 'Unsafe', value: summary.unsafe ?? 0 },
  ]

  return (
    <div>
      <PageHeader
        // `print:hidden` keeps the breadcrumb and the action buttons off the
        // printed sheet — they are page chrome, not part of the report.
        className="print:hidden"
        breadcrumb="Overview"
        title="Reports"
        // THE DESCRIPTION IS DELIBERATELY ABSENT ON THE REPORTS PAGE.
        //
        // It is the longest sentence in the app and on this screen it sat under
        // the heading pushing the filter row and the readings list down, while
        // repeating what the report itself already shows. The requirement is to
        // remove it here; the other screens keep theirs.
        actions={
          // TWO ROWS OF TWO ON A PHONE AND A TABLET, ONE ROW OF FOUR ON DESKTOP.
          //
          // WHAT WAS WRONG. This row was `flex-nowrap`, deliberately, to keep the
          // downloads on one line. On a 360-390px phone that only works if the
          // buttons are allowed to shrink, and `min-w-0` plus `truncate` let them
          // shrink to the point where the labels were clipped mid-word while the
          // four of them still competed for a single line. Forcing one row on a
          // screen with room for two is what produced the cramped, misaligned
          // result - so the row is now a GRID below `lg` and a flex row above it.
          //
          // WHY THE SWITCH IS `lg` AND NOT `sm`. At `sm` the buttons swap to their
          // FULL wording ("Download report as PDF"), and four of those need about
          // 767px. Measured, that overflows a 640px viewport and still overflows
          // 768px once the page padding is taken off. So a `sm` breakpoint would
          // have fixed phones and left tablets broken - the overflow just moved
          // rather than disappearing. `lg` is the first width at which one row
          // genuinely fits, and the grid keeps the short labels until then.
          //
          // `grid grid-cols-2` pins the buttons to exactly two columns, so
          // buttons 1 and 2 take the first row and 3 and 4 the second, and no
          // amount of label length can make a third column or break the pairing.
          // `w-full` lets the grid use the header's full width rather than
          // shrinking to fit its content - which is what produced the earlier
          // cramping. Each cell is `min-w-0` so a long label truncates INSIDE its
          // own button rather than pushing the grid wider.
          //
          // `lg:flex` returns the desktop layout to exactly what it was: four
          // buttons, one line, right-aligned, full wording.
          <div className="print:hidden">
            <div className="grid w-full grid-cols-2 items-center gap-2 lg:flex lg:w-auto lg:flex-nowrap lg:pt-7">
              {/* PDF of the CURRENTLY SELECTED report, as a real downloaded file. */}
              <Button
                onClick={() => exportOnePdf(selected)}
                disabled={!selected}
                className={`${DL_BUTTON} min-w-0`}
              >
                <Icon path="M6 9V3h12v6M6 18H4v-6h16v6h-2M6 14h12v7H6z" className="h-4 w-4 shrink-0" />
                {/* Short on a phone, full wording from `sm` up. */}
                <span className="truncate">
                  <span className="lg:hidden">This PDF</span>
                  <span className="hidden lg:inline">Download report as PDF</span>
                </span>
              </Button>
              {/* EVERYTHING on screen as one PDF. One reading per page, and the
                  export follows the on-screen filter. */}
              <Button
                onClick={exportAllPdf}
                disabled={filtered.length === 0}
                className={`${DL_BUTTON} min-w-0`}
              >
                <Icon path="M6 9V3h12v6M6 18H4v-6h16v6h-2M6 14h12v7H6z" className="h-4 w-4 shrink-0" />
                <span className="truncate">
                  <span className="lg:hidden">All PDF</span>
                  <span className="hidden lg:inline">Download all as PDF</span>
                </span>
              </Button>
              {/* Everything on screen as one CSV. */}
              <Button
                onClick={exportAllCsv}
                disabled={filtered.length === 0}
                className={`${DL_BUTTON} min-w-0`}
              >
                <Icon path="M12 3v12m0 0 4-4m-4 4-4-4M4 19h16" className="h-4 w-4 shrink-0" />
                <span className="truncate">
                  <span className="lg:hidden">All CSV</span>
                  <span className="hidden lg:inline">Download all CSV</span>
                </span>
              </Button>
              {/* --- Reports to Mail: a SIDE ACTION beside the downloads ---

                  Opens the email-entry modal below. It shares the download
                  buttons' black-pill look so the header reads as one action row,
                  and stays ENABLED even with no rows (the modal does not depend
                  on a selection - this step only collects the address). */}
              <Button
                onClick={openMailModal}
                className={`${DL_BUTTON} min-w-0`}
              >
                <Icon
                  path="M3 5h18v14H3zM3 6l9 7 9-7"
                  className="h-4 w-4 shrink-0"
                />
                <span className="truncate">
                  <span className="lg:hidden">Mail</span>
                  <span className="hidden lg:inline">Reports to Mail</span>
                </span>
              </Button>
            </div>
          </div>
        }
      />

      {/* --- Reports to Mail modal -------------------------------------

          A SMALL, PROFESSIONAL EMAIL-ENTRY SECTION. It renders only when the
          side action button has been clicked, overlays the page with a dimmed
          backdrop, and closes on the X button or on a backdrop click. There is
          NO SEND in this step: pressing [ Enter ] only VALIDATES the address
          and shows the outcome inline — a green acknowledgement when it looks
          like an email address, a red message when it does not. */}
      {mailOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 print:hidden"
          onClick={closeMailModal}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="reports-to-mail-title"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl dark:bg-slate-800"
          >
            <div className="flex items-start justify-between gap-3">
              <h2
                id="reports-to-mail-title"
                className="text-base font-semibold text-slate-900 dark:text-white"
              >
                Reports to Mail
              </h2>
              <button
                type="button"
                onClick={closeMailModal}
                aria-label="Close"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-field text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-200"
              >
                <Icon path="M6 6l12 12M18 6L6 18" className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Enter the email address the reports should be sent to.
            </p>

            <form onSubmit={submitMail} noValidate className="mt-4">
              <label
                htmlFor="reports-mail-email"
                className="block text-xs font-medium text-slate-700 dark:text-slate-200"
              >
                Email Address
              </label>
              <input
                id="reports-mail-email"
                type="email"
                autoComplete="email"
                placeholder="Enter email address"
                value={mailEmail}
                onChange={(event) => {
                  setMailEmail(event.target.value)
                  // Clearing the old verdict as soon as typing resumes keeps
                  // the message from contradicting what is in the field.
                  if (mailError) setMailError('')
                  if (mailAccepted) setMailAccepted(false)
                }}
                aria-invalid={mailError ? 'true' : undefined}
                aria-describedby={mailError ? 'reports-mail-error' : undefined}
                className={`mt-1 w-full rounded-field border px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 dark:text-white dark:placeholder:text-slate-500 ${
                  mailError
                    ? 'border-red-500 focus:ring-red-500/40'
                    : 'border-slate-300 focus:border-aqua-500 focus:ring-aqua-500/40 dark:border-slate-600'
                }`}
              />
              {mailError && (
                <p
                  id="reports-mail-error"
                  role="alert"
                  className="mt-1.5 text-xs font-medium text-red-600 dark:text-red-400"
                >
                  {mailError}
                </p>
              )}
              {mailAccepted && (
                <p
                  role="status"
                  className="mt-1.5 text-xs font-medium text-safe-dark dark:text-safe-light"
                >
                  Email address looks valid. Pick an option below, then Send.
                  </p>
              )}

              <div className="mt-4 flex justify-end">
                <Button type="submit" className={DL_BUTTON}>
                  <span className="truncate">Enter</span>
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* --- Download Reports to Our Mail (options popup) ---------------

          OPENS ONLY AFTER A VALID EMAIL + [ Enter ]: `mailAccepted` gates it.
          It is a SECOND, separate popup — the email modal stays underneath —
          and the flow is: pick ONE of the four export options (radio group,
          single selection), then Send. Send is DISABLED until an option is
          chosen, and clicking it does not email anything in this step — it
          shows an inline acknowledgement instead. */}
      {mailOpen && mailAccepted && (
        <div
          className={`fixed inset-0 flex items-center justify-center bg-black/50 p-4 transition-opacity duration-300 print:hidden ${
            mailFading ? 'pointer-events-none opacity-0' : 'opacity-100'
          } z-[60]`}
          onClick={mailSent ? undefined : closeMailModal}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="reports-mail-options-title"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl dark:bg-slate-800"
          >
            {/* --- THE SUCCESS PHASE -------------------------------------
                Shown ONLY after the backend's own `status === "sent"` — never
                on a failure, never speculatively. The four options and the
                Send button are replaced by the single confirmation line,
                which holds for 2 seconds; the backdrop then fades out (the
                `mailFading` opacity transition above) and the popup closes
                when the fade completes. Backdrop clicks and the X are
                disabled during this phase so the message can't be dismissed
                mid-hold. */}
            {mailSent ? (
              <div className="flex items-center justify-center gap-2 py-6 text-center">
                <Icon
                  path="M20 6L9 17l-5-5"
                  className="h-6 w-6 shrink-0 text-safe-dark dark:text-safe-light"
                />
                <p
                  role="status"
                  className="text-sm font-semibold text-safe-dark dark:text-safe-light"
                >
                  Mail sent successfully
                </p>
              </div>
            ) : (
              <>
            <div className="flex items-start justify-between gap-3">
              <h2
                id="reports-mail-options-title"
                className="text-base font-semibold text-slate-900 dark:text-white"
              >
                Download Reports to Our Mail
              </h2>
              <button
                type="button"
                onClick={closeMailModal}
                aria-label="Close"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-field text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-200"
              >
                <Icon path="M6 6l12 12M18 6L6 18" className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Choose what to send to <span className="font-medium">{mailEmail.trim()}</span>.
            </p>

            {/* FOUR OPTIONS, ONE SELECTABLE AT A TIME. A real radio group
                (name shared, `role=radiogroup`) gives the single-choice rule
                for free, keyboard support included. Each row is its own
                label so clicking anywhere on the row selects it. */}
            {/* THE TWO "REPORT" OPTIONS NEED A SELECTION: they attach the
                CURRENTLY SELECTED REPORT, so with no report selected they are
                disabled and "Please select a report first." explains why. The
                two "ALL" options cover everything on screen and stay usable. */}
            {!selected && (
              <p role="status" className="mt-3 text-xs font-medium text-caution-dark dark:text-caution-light">
                Please select a report first.
              </p>
            )}
            <div role="radiogroup" aria-label="Report export options" className="mt-4 space-y-2">
              {[
                { key: 'report_pdf', label: 'Download Report PDF', needsReport: true },
                { key: 'report_csv', label: 'Download Report CSV', needsReport: true },
                { key: 'all_pdf', label: 'Download All PDF', needsReport: false },
                { key: 'all_csv', label: 'Download All CSV', needsReport: false },
              ].map((option) => {
                const active = mailChoice === option.key
                const unusable = option.needsReport && !selected
                return (
                  <label
                    key={option.key}
                    className={`flex items-center gap-3 rounded-field border px-3 py-2.5 text-sm transition-colors ${
                      unusable
                        ? 'cursor-not-allowed border-slate-200 opacity-50 dark:border-slate-600'
                        : active
                          ? 'cursor-pointer border-aqua-500 bg-aqua-50 dark:border-aqua-500 dark:bg-aqua-900/30'
                          : 'cursor-pointer border-slate-200 hover:border-slate-300 dark:border-slate-600 dark:hover:border-slate-500'
                    }`}
                  >
                    <input
                      type="radio"
                      name="reports-mail-option"
                      value={option.key}
                      checked={active}
                      disabled={unusable}
                      onChange={() => {
                        setMailChoice(option.key)
                        setMailNote('')
                        setMailAttachError('')
                      }}
                      className="h-4 w-4 shrink-0 accent-aqua-600"
                    />
                    <span
                      className={`font-medium ${
                        unusable
                          ? 'text-slate-400 dark:text-slate-500'
                          : 'text-slate-800 dark:text-slate-100'
                      }`}
                    >
                      {option.label}
                      {unusable && (
                        <span className="ml-2 text-2xs font-normal text-slate-400 dark:text-slate-500">
                          (no report selected)
                        </span>
                      )}
                    </span>
                  </label>
                )
              })}
            </div>

            {mailNote && (
              <p role="status" className="mt-3 text-xs font-medium text-safe-dark dark:text-safe-light">
                {mailNote}
              </p>
            )}

            {mailAttachError && (
              <p role="alert" className="mt-3 text-xs font-medium text-red-600 dark:text-red-400">
                {mailAttachError}
              </p>
            )}

            {/* SEND: DISABLED until one option is selected (`!mailChoice`), and
                while a send is in flight — so a duplicate click can never fire
                a second API call. The label switches to "Sending..." for the
                duration. */}
            <div className="mt-4 flex justify-end">
              <Button
                type="button"
                onClick={sendMailChoice}
                disabled={!mailChoice || mailSending}
                className={`${DL_BUTTON} disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 disabled:hover:bg-slate-300 disabled:hover:text-slate-500 dark:disabled:bg-slate-600 dark:disabled:text-slate-400`}
              >
                <span className="truncate">{mailSending ? 'Sending...' : 'Send'}</span>
              </Button>
            </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* --- Verdict filter ---

          `flex` is what actually puts the chips in a row; without it they were
          block-level and stacked.

          ONE ROW ON A PHONE. `flex-nowrap` keeps all four chips on a single line
          and they shrink to fit (`min-w-0` + a small `px`) instead of wrapping
          into a two-row block that pushed the readings list off the first
          screen. The "Show" caption is hidden on a phone — it is a label, and
          the chips are self-evident — which is what frees the width for them, and
          each chip takes an equal share (`flex-1`) so they come out the same
          size rather than sized to their text. */}
      {/* EVEN GAPS BETWEEN THE CHIPS, on every viewport.

          `flex` is LOAD-BEARING and was the actual bug. The previous class list
          had `flex-nowrap` but no `flex`, so the container was a plain block and
          the chips sat in it with the gap applying to nothing -- which is exactly
          why there appeared to be no space between them. With `flex` present,
          `gap-2` (mobile) and `gap-3` (desktop) put a real space between the pill
          buttons, and `flex-wrap` lets them drop to a second row on a very narrow
          phone rather than being crushed together. Each chip is padded
          (`px-3`/`px-4`) so the gap is visible and the labels are not touching
          their own edges. */}
      {/* `flex` is LOAD-BEARING. Without it `flex-wrap` is inert, the row is a
          plain block, and the chips sit with `gap` applying to nothing — which is
          exactly why there appeared to be no space between them.

          `mt-2` adds ONE LINE OF SPACE between the heading row above and this
          filter row; the two used to sit flush, which read as one crowded block. */}
      <div className="flex flex-wrap items-center gap-2 sm:gap-3 print:hidden mt-2 mb-4">
        <span className="mr-1 hidden text-xs font-semibold uppercase tracking-wider text-slate-500 sm:inline dark:text-slate-300">
          Show
        </span>
        {tiles.map((tile) => (
          <button
            key={tile.label}
            type="button"
            onClick={() => {
              setRiskFilter(tile.key)
              setSelectedId(null)
            }}
            aria-pressed={riskFilter === tile.key}
            /* DARK-MODE HOVER IS A WHITE BUTTON WITH BLACK TEXT — the same
               inversion the secondary button uses — so hovering a filter chip
               lifts it off the dark page instead of shading it a darker grey.
               The inactive light-mode chip keeps its pale slate hover. */
            className={`min-w-0 truncate rounded-full px-3 py-1.5 text-2xs font-medium transition-colors sm:px-4 sm:py-2 sm:text-xs ${riskFilter === tile.key
                ? 'bg-aqua-600 text-white shadow-sm dark:bg-aqua-700'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-white dark:hover:text-black'
              }`}
          >
            {tile.label}
            <span className="ml-1 opacity-70 tabular">{tile.value}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        {/* --- The list of readings --- */}
        <Card
          title="Readings"
          subtitle={`${filtered.length} record${filtered.length === 1 ? '' : 's'}`}
          padded={false}
          className="print:hidden"
        >
          {history.loading ? (
            <Spinner label="Loading readings…" />
          ) : history.error ? (
            <div className="p-5">
              <ErrorState message={history.error} onRetry={history.refetch} />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              title="No readings"
              description="Submit a water sample and it will appear here as a report."
              icon={<Icon path={ICONS.history} className="h-7 w-7" />}
            />
          ) : (
            <ul className="max-h-[32rem] divide-y divide-slate-100 overflow-y-auto">
              {filtered.map((row) => {
                const isActive = selected?.id === row.id
                return (
                  <li
                    key={row.id}
                    className={`flex items-center gap-2 px-5 py-3 transition-colors ${isActive
                        ? 'bg-aqua-50 dark:bg-aqua-900/30'
                        : 'hover:bg-slate-50 dark:hover:bg-black/70'
                      }`}
                  >
                    {/* The row body selects the report; a SEPARATE button
                        downloads just this one. They are siblings, not nested,
                        because a <button> inside a <button> is invalid HTML and
                        the inner click could not be told apart from the outer
                        one. */}
                    <button
                      type="button"
                      onClick={() => setSelectedId(row.id)}
                      aria-current={isActive ? 'true' : undefined}
                      className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-mono text-xs text-slate-500 dark:text-slate-400">
                          {reportId(row)}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-400 tabular">
                          {formatPredictionStamp(row.created_at).combined}
                        </span>
                      </span>
                      {/* THE VERDICT IS A LIGHT COLOURED BUTTON here: pale
                          red for unsafe, pale amber for moderate, pale green for
                          safe — a matching border, and never a saturated block.
                          Scanning the list, the colours read immediately without
                          shouting. */}
                      <Badge risk={row.prediction} button />
                    </button>

                    {/* Download JUST this report, in EITHER format, with no
                        touch or click on anything else required. Two sibling
                        buttons, not nested, so each click is unambiguous. */}
                    <button
                      type="button"
                      onClick={() => exportOnePdf(row)}
                      aria-label={`Download ${reportId(row)} as PDF`}
                      title="Download this report as PDF"
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-field text-slate-400 transition-colors hover:bg-aqua-600 hover:text-white dark:hover:bg-white dark:hover:text-black"
                    >
                      <Icon path="M6 9V3h12v6M6 18H4v-6h16v6h-2M6 14h12v7H6z" className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => exportOneCsv(row)}
                      aria-label={`Download ${reportId(row)} as CSV`}
                      title="Download this report as CSV"
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-field text-slate-400 transition-colors hover:bg-aqua-600 hover:text-white dark:hover:bg-white dark:hover:text-black"
                    >
                      <Icon path="M12 3v12m0 0 4-4m-4 4-4-4M4 19h16" className="h-4 w-4" />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>

        {/* --- The report itself --- */}
        {selected ? (
          // CENTRED IN ITS COLUMN ON DESKTOP.
          //
          // The right-hand column is `minmax(0,1fr)` — much wider than the
          // report card needs — so the card sat pinned to the LEFT edge with a
          // band of empty space beside it, which read as a layout mistake. The
          // wrapper below is a flex row with `justify-center` and a max width, so
          // the sheet is centred in the space it has while still shrinking to
          // fit on a narrow screen. On mobile it is a single column and the
          // centring is a no-op.
          <div className="flex justify-center">
            <div className="w-full max-w-[46rem]">
              <ReportSheet row={selected} />
            </div>
          </div>
        ) : (
          <Card>
            <EmptyState
              title="Nothing to report"
              description="Choose a reading from the list to see its full report."
              icon={<Icon path={ICONS.analytics} className="h-7 w-7" />}
            />
          </Card>
        )}
      </div>
    </div>
  )
}

/**
 * One reading as a document.
 *
 * Structured as a report rather than as a screenshot of a card: an identity
 * header, the verdict, a parameter table with the reference band beside each
 * value, and a footnote. That ordering is what makes the printed sheet readable
 * on its own, detached from the app.
 */
export function ReportSheet({ row }) {
  const created = row.created_at

  return (
    <Card className="print-sheet print:border-0 print:shadow-none">
      {/* --- Masthead: the brand, centred, with the droplet ----------------
          This is the top of the printed page as well as the top of the card: the
          mark and wordmark sit centred above the report ID, so the sheet is
          identifiable as an AquaGuard document on its own, detached from the
          app. On screen it also gives the report a clear starting point instead
          of dropping the reader straight into an ID string. */}
      {/* --- Masthead: the report's own title line -------------------------

          THIS IS WHERE THE PRINTED PAGE STARTS. The report ID, the verdict and
          the metadata used to sit ABOVE this block, wrapped in rules that printed
          as grey horizontal lines across the top of the sheet. Those bands have
          been removed: the page now opens on the document's title, exactly as
          the requirement asks, and the ID and metadata follow underneath as
          ordinary text rather than as a bordered header strip.

          The droplet is INLINE — a small mark before the words "AquaGuard AI",
          on the same baseline — rather than a badge centred above them. That
          matches the way the brand is written everywhere else in the app and
          removes the second, large drop that used to dominate the masthead. */}
      <header className="print-masthead">
        <div className="flex flex-col items-center gap-1 text-center">
          <h2 className="flex items-center justify-center gap-2 text-lg font-semibold tracking-tight text-slate-900 dark:text-white">
            <span
              className="print-keep flex h-6 w-6 items-center justify-center text-aqua-600 dark:text-aqua-300"
              aria-hidden="true"
            >
              <Icon path={ICONS.droplet} className="h-5 w-5" />
            </span>
            AquaGuard AI — Water Quality Monitoring &amp; Prediction
          </h2>
          <p className="text-2xs font-semibold uppercase tracking-[0.18em] text-aqua-700 dark:text-aqua-300">
            Water Quality Report
          </p>
        </div>

        <div className="mt-4 flex items-center justify-center gap-3">
          <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">
            {reportId(row)}
          </span>
          {/* COLOURED VERDICT ON THE REPORT SHEET (red / yellow / green).

              `button` gives the same red-unsafe / yellow-moderate / green-safe
              pill the readings list uses, so the sheet and the list agree. It is
              on the sheet rather than only in the list because this card is what
              the printed page and the PDF are built from — the verdict has to
              carry its colour onto paper too, and the `@media print` block keeps
              the badge tint while stripping everything else. */}
          <Badge risk={row.prediction} button />
        </div>

        <dl className="mt-4 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          <Meta label="Report ID" value={reportId(row)} mono />
          <Meta label="Prediction ID" value={predictionId(row)} mono />
          <Meta label="Date" value={formatPredictionStamp(created).date} />
          <Meta label="Time" value={formatPredictionStamp(created).time} />
          {/* The place the sample came from, as a label — not raw coordinates.
              Area, city, pincode, district, state and country come from the row
              itself; a missing pincode is "Not Available", never guessed. */}
          <Meta label="Location" value={reportLocation(row) || 'Not recorded'} />
          <Meta label="Area" value={row.location_area || 'Not Available'} />
          <Meta label="City / Town" value={row.location_city || 'Not Available'} />
          <Meta
            label="Pincode"
            value={row.location_pincode ? String(row.location_pincode) : 'Not Available'}
          />
          <Meta label="District" value={row.location_district || 'Not Available'} />
          <Meta label="State" value={row.location_state || 'Not Available'} />
          <Meta label="Country" value={row.location_country || 'Not Available'} />
          {/* PROMPT 4: the stored source type, or the nearest real nearby
              source with its real distance, or an explicit "unavailable" —
              never a plausible-looking substitute. */}
          <Meta label="Water Source" value={waterSourceLabel(row)} />
          {row.nearby_water_source && (
            <Meta
              label="Nearest Source"
              value={[
                row.nearby_water_source,
                row.nearby_water_source_distance != null
                  ? `${Number(row.nearby_water_source_distance)} km away`
                  : null,
              ]
                .filter(Boolean)
                .join(' — ')}
            />
          )}
          <Meta label="Verdict" value={String(row.prediction || '').toUpperCase()} />
          <Meta
            label="Risk"
            value={{ safe: 'Low', moderate: 'Medium', unsafe: 'High' }[row.prediction] || 'Not Available'}
          />
          <Meta label="Confidence" value={formatPercent(row.confidence)} />
        </dl>
      </header>

      {/* --- Parameters against their normal ranges --- */}
      <div className="mt-5">
        <h3 className="text-[0.9375rem] font-semibold text-slate-900 dark:text-white">
          Measured parameters
        </h3>
        {/* The explanatory sentence is desktop-only: on a phone it is three
            lines of small print above a table that is the point of the block. */}
        <p className="mt-0.5 hidden text-xs text-slate-500 sm:block dark:text-slate-400">
          The normal range is the standard drinking-water reference band, shown for
          comparison. The verdict above comes from the model, not from these bands.
        </p>

        {/* FITS THE CARD ON BOTH EDGES, ON EVERY VIEWPORT, WITH NO HORIZONTAL
            SCROLL.

            The table carried `min-w-[34rem]` from the shared `.table` class, and
            the wrapper was `-mx-5` (a negative margin bleeding it past the card's
            padding). Together those forced a scrollbar and left the table sitting
            proud of the card on the right — the "left is aligned but the right is
            ragged, with a gap" the user described.

            Three things fix it, and none of them is a scroll:

              `!min-w-0`  overrides the shared 34rem floor for THIS table only, so
                          it can lay out to the real, narrower card width instead
                          of demanding a scrollbar. Applied at BOTH breakpoints
                          (`sm:` included) so the desktop report card — which is
                          narrow because it sits beside the readings list — does
                          not scroll either.
              `table-fixed` divides that width into equal columns, so the first
                          column's left edge and the last column's right edge sit
                          on straight, predictable lines rather than drifting with
                          the content.
              no `-mx-5`  the wrapper keeps the card's own padding, so the table's
                          edges align with the card's content box exactly — flush
                          on the left and the right, stable as the report changes. */}
        <div className="table-wrap mt-3 report-table-wrap">
          <table className="table !min-w-0 table-fixed report-table">
            <thead>
              <tr>
                <th scope="col">Parameter</th>
                <th scope="col">Measured</th>
                <th scope="col">Normal range</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {PARAMETER_ORDER.map((key) => {
                const band = NORMAL_LEVELS[key]
                const status = classifyReading(key, row[key])
                return (
                  <tr key={key}>
                    <td className="align-top">
                      {/* FULL LABEL FROM `sm` UP, SHORT SYMBOL ON A PHONE.

                          "Total Dissolved Solids" in a ~90px column wrapped to
                          three lines and made its row taller than every other,
                          which is what pulled the mobile table out of alignment.
                          The symbol (`TDS`, `DO`, `Temp`, `Turb`) keeps every row
                          the same height and still names the parameter beyond
                          doubt. */}
                      <span className="block font-medium text-slate-800 dark:text-slate-100">
                        <span className="sm:hidden">{band.symbol}</span>
                        <span className="hidden sm:inline">{band.label}</span>
                      </span>
                      {/* The unit repeats the unit already inside "Normal
                          range", and on a phone it doubles the height of every
                          row. Hidden below `sm`. */}
                      <span className="block text-2xs text-slate-400 max-sm:hidden">
                        {band.unit}
                      </span>
                    </td>
                    <td className="align-top font-medium tabular">
                      {/* THE UNIT SITS WITH THE READING ON A PHONE, so the
                          "Measured" column is self-describing without a second
                          line: the value and its unit are one compact token. */}
                      {formatNumber(row[key])}
                      <span className="ml-0.5 text-2xs font-normal text-slate-400 sm:ml-0 sm:block">
                        {band.unit}
                      </span>
                    </td>
                    <td className="align-top tabular text-slate-600 dark:text-slate-300">
                      {normalRangeText(key)}
                      <span className="block max-sm:hidden text-2xs text-slate-400">
                        {band.unit}
                      </span>
                    </td>
                    {/* Right-aligned on a phone from the scoped CSS rule, so the
                        chip sits in the card's right corner rather than floating
                        mid-cell. Left-aligned from `sm` up. */}
                    <td className="align-top">
                      <StatusChip status={status} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* The plain-language meaning of each band, kept BELOW the table so it
            explains the numbers rather than delaying them. */}
        <ul className="mt-4 space-y-1.5">
          {PARAMETER_ORDER.map((key) => (
            <li key={key} className="text-xs text-slate-500 dark:text-slate-400">
              <span className="font-medium text-slate-600 dark:text-slate-300">
                {NORMAL_LEVELS[key].label}:
              </span>{' '}
              {NORMAL_LEVELS[key].note}
            </li>
          ))}
        </ul>
      </div>

      {/* --- Instructions: what to do next -------------------------------

          Sits directly under the measured parameters, keyed to the verdict, so
          the reader gets the action as well as the number. A report that only
          tells you a reading is bad leaves the most important question — what do
          I do now — unanswered. */}
      <div className="mt-5 print:hidden">
        <h3 className="text-[0.9375rem] font-semibold text-slate-900 dark:text-white">
          What to do next
        </h3>
        <ol className="mt-2 space-y-2">
          {(VERDICT_STEPS[String(row.prediction)] || VERDICT_STEPS.safe).map(
            (line, index) => (
              <li
                key={line}
                className="flex gap-2.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300"
              >
                {/* THE STEP NUMBER IS A RINGED DISC, not a bare digit.

                    It was `h-4.5 w-4.5` — and 4.5 is NOT in Tailwind's spacing
                    scale, so the class emitted nothing and the span collapsed to
                    the width of its single digit with no circle around it. A real
                    scale value (`h-5 w-5`) plus `rounded-full` and a ring gives
                    the number a proper circle to sit in, at every breakpoint. */}
                <span
                  className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-aqua-100 text-[0.625rem] font-bold leading-none text-aqua-700 ring-1 ring-aqua-300 dark:bg-aqua-900 dark:text-aqua-100 dark:ring-aqua-600"
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
                {line}
              </li>
            ),
          )}
        </ol>

        <h3 className="mt-5 text-[0.9375rem] font-semibold text-slate-900 dark:text-white">
          Reading and sampling notes
        </h3>
        <ul className="mt-2 space-y-1.5">
          {GENERAL_INSTRUCTIONS.map((line) => (
            <li
              key={line}
              className="text-xs leading-relaxed text-slate-500 dark:text-slate-400"
            >
              {line}
            </li>
          ))}
        </ul>
      </div>

      {/* The closing disclaimer is hidden on a phone. It is four lines of the
          smallest text on the page, sitting under the thing the reader came for,
          and it pushes the end of the report off the screen. It stays in the
          printed/PDF output and on desktop. */}
      <p className="mt-5 hidden border-t border-slate-200 pt-4 text-2xs text-slate-500 sm:block dark:border-slate-700 dark:text-slate-400">
        AquaGuard AI is a screening tool. This report is generated from five
        measured parameters and a statistical model; it is not a laboratory
        analysis and must not be treated as one. Confidence is the model&rsquo;s
        strength of opinion about this sample, not a measure of accuracy.
      </p>
    </Card>
  )
}

/** One label/value pair in the report header. */
function Meta({ label, value, mono = false }) {
  return (
    <div className="flex justify-between gap-3 sm:block">
      <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
      <dd
        className={`font-medium text-slate-800 dark:text-slate-100 ${mono ? 'font-mono' : ''}`}
      >
        {value}
      </dd>
    </div>
  )
}

/** The reading's position against its healthy band. */
function StatusChip({ status }) {
  const tones = {
    normal: 'bg-safe-light text-safe-dark',
    low: 'bg-caution-light text-caution-dark',
    high: 'bg-unsafe-light text-unsafe-dark',
    unknown: 'bg-slate-100 text-slate-600',
  }
  // SHORT ON A PHONE, FULL FROM `sm` UP, SAME CHIP IN BOTH.
  //
  // "Below normal" / "Above normal" are the longest strings in this column and
  // they wrapped onto two lines inside the narrow mobile column, which made one
  // row taller than its neighbours and pushed the table out of alignment. The
  // one-word form ("Below", "Above", "In range") keeps every row the same height
  // on a phone, while the exported CSV/PDF keeps the full wording it already had
  // - `READING_WORDS_SHORT` is a display-only map and never reaches an export.
  //
  // Both wordings are rendered and swapped by breakpoint rather than chosen in
  // JS from a media query, so this stays a pure component with no listener.
  // `whitespace-nowrap` keeps each on ONE line at every width.
  return (
    <span className={`badge whitespace-nowrap ${tones[status] || tones.unknown}`}>
      <span className="sm:hidden">{READING_WORDS_SHORT[status]}</span>
      <span className="hidden sm:inline">{READING_WORDS[status]}</span>
    </span>
  )
}


