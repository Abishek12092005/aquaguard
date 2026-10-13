/**
 * API surface for the client — one module per backend resource.
 *
 * Every function returns the backend's `data` payload directly. Errors are
 * already normalised by the Axios interceptor in `client.js`.
 */

import { api } from '@/api/client'
import { ROUTES } from '@/utils/constants'

/* -------------------------------------------------------------------------- */
/* Health                                                                      */
/* -------------------------------------------------------------------------- */
export const healthApi = {
  check: () => api.get('/health'),
  checkDatabase: () => api.get('/health/database'),
}

/* -------------------------------------------------------------------------- */
/* Predictions                                                                 */
/* -------------------------------------------------------------------------- */
export const predictionApi = {
  /**
   * Submit the five parameters and receive a prediction.
   *
   * The model-first endpoint: it validates, runs the trained Random Forest,
   * persists the result (user_id, parameters, prediction, confidence,
   * timestamp) and returns the verdict with a confidence score.
   */
  predict: (features) => api.post('/predictions/predict', features),
  /** Stored-row variant, kept for callers that want the raw history shape. */
  create: (features) => api.post('/predictions', features),
  /**
   * Paginated prediction history for the signed-in user.
   *
   * `params` accepts page, per_page, risk_level, search and sort. All of them
   * are applied by the server across the whole history, so paging and filtering
   * give consistent answers rather than only filtering the visible page.
   */
  history: (params) => api.get('/predictions/history', { params }),
  /** Same records as `history`, kept for existing callers. */
  list: (params) => api.get('/predictions', { params }),
  /**
   * Email the signed-in user's own report(s) as an attachment.
   *
   * Resolves with the backend's response envelope; success is claimed ONLY when
   * the mail transport itself returned "sent" (HTTP 200). The backend owns the
   * truth — the UI never fabricates a success message.
   */
  mailReports: (payload) => api.post('/reports/mail', payload),
  /**
   * Download one report as a PDF built by the SAME server-side generator the
   * mail attachment uses — one layout, one timestamp path, one watermark, so a
   * downloaded report and an emailed one can never disagree.
   */
  downloadReportPdf: (id) => api.get(`/reports/pdf/${id}`, { responseType: 'blob' }),
  /**
   * Download EVERY report the account owns as one PDF.
   *
   * Built by the SAME server-side `build_pdf` the mail attachment and the
   * single-report download use, so all three carry identical data, the same
   * stored timestamp, the same formatting and the same watermark.
   */
  downloadAllReportsPdf: () => api.get('/reports/pdf', { responseType: 'blob' }),
  /**
   * The account's verdict counts, counted from the real stored records.
   *
   * The Reports filter chips read these rather than tallying the rows the page
   * happened to fetch, so the numbers always describe the whole history.
   */
  counts: () => api.get('/predictions/counts'),
  latest: () => api.get('/predictions/latest'),
  stats: (range = '30d') => api.get('/predictions/stats', { params: { range } }),
  getById: (id) => api.get(`/predictions/${id}`),
  remove: (id) => api.delete(`/predictions/${id}`),
}

/* -------------------------------------------------------------------------- */
/* Dashboard                                                                   */
/* -------------------------------------------------------------------------- */
export const dashboardApi = {
  overview: () => api.get('/dashboard/overview'),
  charts: () => api.get('/dashboard/charts'),
  summary: () => api.get('/dashboard/summary'),
  recent: (limit = 5) => api.get('/dashboard/recent', { params: { limit } }),
  /**
   * Authoritative parameter metadata (order, labels, units, bounds).
   * The prediction form builds itself from this, so the UI can never drift
   * from the backend's validation and model contract.
   */
  parameters: () => api.get('/dashboard/parameters'),
}

/* -------------------------------------------------------------------------- */
/* Alerts                                                                      */
/* -------------------------------------------------------------------------- */
export const alertApi = {
  /** Paginated alerts. `params` accepts page, per_page, status, severity. */
  list: (params) => api.get('/alerts', { params }),
  summary: () => api.get('/alerts/summary'),
  /** Mark one alert read. Idempotent; resolves to `changed: true|false`. */
  markRead: (id) => api.patch(`/alerts/${id}/read`),
  /** Mark every unread alert read. */
  markAllRead: () => api.patch('/alerts/read-all'),
  /** Alias of `markRead`, kept for callers already using the older path. */
  acknowledge: (id) => api.patch(`/alerts/${id}/ack`),
  resolve: (id) => api.patch(`/alerts/${id}/resolve`),
  /** Reopen a resolved alert. The undo for `resolve`. */
  unresolve: (id) => api.patch(`/alerts/${id}/unresolve`),
}

/* -------------------------------------------------------------------------- */
/* Location                                                                    */
/* -------------------------------------------------------------------------- */
/**
 * Location-based water quality lookups.
 *
 * These endpoints only RESOLVE a location: they search a place, reverse-geocode
 * the device's coordinates, and return the water source, nearby sources with
 * distances, risk factors and a set of default prediction parameters. Nothing
 * here predicts — `predictionApi.predict` is still the one path through the
 * Random Forest, and `/locations/parameters` merely pre-fills that form.
 */
export const locationApi = {
  /** Find a place by name, pincode or landmark. `params` = { q, limit, autocomplete }. */
  search: (params) => api.get('/locations/search', { params }),
  /**
   * Resolve a single location for the search bar, or reject it.
   *
   * `query` is a place name, a pincode or a famous landmark. Resolves to the one
   * best match, or a 404 the caller shows as "no location found" — which is how
   * an invalid or unsupported location is refused rather than guessed at.
   *
   * STEP 22: a BARE VILLAGE NAME is answered 200 as well, but with a
   * disambiguation payload (`requires_district: true` plus the candidate villages)
   * instead of a place — the user has to say which village and district they mean
   * before any water-quality result is produced. Every non-village search (city,
   * town, area, nagar, colony, company, shop, college, school, hotel, hospital,
   * landmark) is unaffected.
   *
   * `options.allowAmbiguous` sets `allow_ambiguous` on the request, which is how
   * a village the user has ALREADY qualified ("Kothanallur, Kalkulam") or picked
   * from the disambiguation list skips the gate. It is never set on a bare name.
   */
  resolve: (query, options) =>
    api.get('/locations/resolve', {
      params: { q: query, ...(options?.allowAmbiguous ? { allow_ambiguous: 1 } : {}) },
    }),
  /** Resolve device coordinates into an address. `params` = { lat, lon }. */
  reverse: (params) => api.get('/locations/reverse', { params }),
  /**
   * STEP 23: identify the area behind a typed PINCODE.
   *
   * A pincode is an address, not a place name, so it gets its own endpoint rather
   * than going through the text search - which, measured, answered "999999" with
   * a railway station in Italy and "12345" with a rural council in Ukraine.
   *
   * Returns the identified place (area, city/town, district, state, country and
   * the pincode itself), each field either a real value from the postal data or
   * null for "not available". When the pincode covers several areas, `areas`
   * holds all of them so the user can choose rather than one being picked for
   * them. A 422 means the text is not a valid PIN code; a 404 means the postal
   * data does not know it. Neither ever falls back to a name search.
   */
  pincode: (q) => api.get('/locations/pincode', { params: { q } }),
  /**
   * The water source at a location, and the sources near it.
   *
   * `params` accepts EITHER { lat, lon } OR { name }. Returns the resolved place,
   * an `available` flag, the `primary` water type (the nearest real source), the
   * `types` observed nearby, and the `nearby` list with real names and distances.
   * When `available` is false the response carries an honest `message` instead of
   * an invented source.
   */
  water: (params) => api.get('/locations/water', { params }),
  /**
   * Everything known about a place's water in one call.
   *
   * `params` accepts EITHER { lat, lon } OR { name }. Coordinates win when both
   * are supplied. Returns the place, water context, rain, risks and default
   * parameters.
   */
  context: (params) => api.get('/locations/context', { params }),
  /**
   * The country-level overview: every state under one country, each with ONE
   * aggregated water-quality risk indicator.
   *
   * `params` = { q, limit }. The risk is CALCULATED from the mapped water data
   * at each state's centre (same derivation as `/context`), never randomly
   * assigned — a state with no mapped water returns the honest `unknown`.
   * `legend` and `summary` come from the backend so the UI cannot drift.
   */
  country: (params) => api.get('/locations/country', { params }),
  /**
   * The state-level overview (Step 20): every district under one state, each
   * with ONE aggregated water-quality risk indicator, in alphabetical ORDER
   * with a `rank` (01, 02, …). Same calculation contract as `country` — risk
   * is derived from the mapped water data at each district's centre, never
   * randomly assigned, and individual place predictions are NOT exposed here.
   *
   * `params` = { q, limit }.
   */
  state: (params) => api.get('/locations/state', { params }),
  /**
   * The district-level view (Step 21): the nine major / relevant places of one
   * district, gathered into the brief's internal 3 SAFE / 3 MODERATE / 3
   * UNSAFE dataset — but the cards show ONLY place name, town/village/area,
   * district and state. No Safe/Moderate/Unsafe label and no prediction is
   * exposed here; the verdict is revealed when the user clicks a place and the
   * existing analysis path runs.
   *
   * `params` = { q }.
   */
  district: (params) => api.get('/locations/district', { params }),
  /** Default prediction readings for a water source type. `params` = { water_type }. */
  parameters: (waterType) =>
    api.get('/locations/parameters', { params: { water_type: waterType } }),

  /**
   * The rain situation for the STATE the device is in.
   *
   * `params` = { lat, lon } - the browser's OWN geolocation fix, obtained by
   * asking for the permission. The backend reverse-geocodes that point, reads
   * the state out of it, resolves that state's centre by name and forecasts
   * there, so the answer is regional rather than a reading at one doorstep. No
   * state is assumed anywhere in the path.
   *
   * Resolves with the place, the state, the data source and the forecast
   * together, so the screen never has to join two responses. A 404 means the
   * coordinates match no state, which is an honest answer rather than a failure.
   */
  rainAlert: (coords) =>
    api.get('/locations/rain-alert', {
      params: { lat: coords.lat, lon: coords.lon },
    }),

  /**
   * PROMPT 2, B.7-B.9: real rain outlooks for a sample of one state's
   * districts. Send either a state name, or the device coordinates whose state
   * the server reverse-geocodes. Rows are read at each district's own
   * coordinates - never copied from one location's weather.
   */
  regionalAlerts: ({ state, lat, lon } = {}) =>
    api.get('/locations/regional-alerts', {
      params: {
        ...(state ? { state } : null),
        ...(lat != null ? { lat } : null),
        ...(lon != null ? { lon } : null),
      },
    }),
}

/* -------------------------------------------------------------------------- */
/* Admin console                                                               */
/* -------------------------------------------------------------------------- */
/**
 * The admin console API.
 *
 * Mounted at `/api/admin`, NOT under `/api/v1`: it is an internal surface rather
 * than part of the versioned public contract.
 *
 * THE CONSOLE CREDENTIAL IS THE WHOLE OF ITS AUTHENTICATION. Normal users have
 * no login at all, so there is no account session behind this and no token a
 * visitor could already hold: `openSession` checks the console's own username
 * and password, and the mail confirmation is what actually opens the window.
 * Every other endpoint below refuses everything until that window is open.
 */
export const adminApi = {
  /**
   * Sign in to the console with its own username + password.
   *
   * A POST, not a login: it does not issue a token, and it is not anybody's
   * account. It opens a short server-side window for this session only, and
   * only once the mailed confirmation is spent. The username is checked with
   * the password; sending it alone (without a username) still works for any
   * older caller.
   */
  openSession: (payload) => api.post('/admin/session', payload),
  /** Whether the console is open. Public, so the page can decide what to show. */
  sessionState: () => api.get('/admin/session'),
  /**
   * DEPRECATED — the backend's `/session/confirm` now answers 410 and grants
   * nothing. Kept so an old bundle does not crash on a missing method; it can no
   * longer open the console.
   */
  confirmSession: (token) => api.post('/admin/session/confirm', { token }),
  lockSession: () => api.post('/admin/session/lock'),

  /* --------------------------------------------------------------------------
   * The two-step login approval flow (PROMPT 8).
   *
   * The console's login page STAYS OPEN and polls `approvalStatus` until the
   * decision arrives in the mail. Nothing navigates anywhere: the approver acts in
   * their own mail client, and the grant happens back here.
   *
   * `CHALLENGE` is the binding that makes this safe. It is minted once per page
   * load, handed over by `challenge()`, and then lives ONLY in this tab's
   * `sessionStorage` — never in a cookie, never in a URL. A cookie would be sent
   * with any cross-site request (CSRF) and a query parameter would leak into
   * Referer headers, proxy logs and browser history.
   * -------------------------------------------------------------------------- */

  /** Mint this page load's browser challenge. Called once, on first render. */
  challenge: () => api.get('/admin/session/challenge'),
  /** Ask for one approval request. `challenge` is REQUIRED. */
  requestApproval: (payload) => api.post('/admin/session', payload),
  /** The outcome of one request. Scoped by `request_id` AND the challenge. */
  approvalStatus: (payload) => api.post('/admin/session/approval', payload),
  /**
   * Spend an approved request and open the console. This is the ONLY call that can
   * unlock, and the backend re-checks the status, the mail token AND the challenge
   * before it does.
   */
  consumeApproval: (requestId, payload) => api.post(`/admin/session/approval/${requestId}/consume`, payload),

  changePassword: (payload) => api.post('/admin/password', payload),

  /**
   * Mail a 6-digit code to the recovery address, or set a new password with
   * one. These are part of proving the console credential, so they are reachable
   * before it has been proved - which is the point of them.
   */
  forgotPassword: () => api.post('/admin/password/forgot'),
  /** Set a new console password using the emailed code (no old password). */
  resetPassword: (payload) => api.post('/admin/password/reset', payload),
  /**
   * PROMPT 9: verified email management. Request a code to a NEW address, or
   * re-point the approval address at the recovery inbox with no code; then
   * confirm with the code that inbox received.
   */
  requestEmailChange: (payload) => api.post('/admin/email/change/request', payload),
  confirmEmailChange: (payload) => api.post('/admin/email/change/confirm', payload),

  /** The console's own login name and recovery email. */
  identity: () => api.get('/admin/identity'),
  /** Change the login name and/or the recovery email. Requires an unlock. */
  updateIdentity: (payload) => api.put('/admin/identity', payload),

  dashboard: () => api.get('/admin/dashboard'),

  users: (params) => api.get('/admin/users', { params }),
  setUserRole: (id, role) => api.patch(`/admin/users/${id}/role`, { role }),
  /**
   * Delete an account and everything it owns.
   *
   * The cascade lives in the schema, so this is one DELETE rather than a
   * sequence the browser orchestrates — a partial delete cannot happen.
   */
  deleteUser: (id) => api.delete(`/admin/users/${id}`),

  loginDetails: (params) => api.get('/admin/login-details', { params }),
  loginDetailsStats: () => api.get('/admin/login-details/stats'),
  /**
   * PROMPT 12: the report-email audit trail — every processed Reports-to-Mail
   * request, with the recipient, report option, delivery verdict, requester
   * identity and (only when legitimately obtained) the consented location.
   * Server-side paged and filtered; unlocked console required.
   */
  reportEmailAudit: (params) => api.get('/admin/report-email-audit', { params }),
  /**
   * Download the sign-in dataset.
   *
   * `format: 'xlsx'` is honoured by NAME and MIME type; the bytes are still CSV,
   * because producing a real .xlsx needs a spreadsheet library and Excel opens a
   * CSV directly. See the backend route's docstring.
   */
  exportLoginDetails: (params) =>
    api.get('/admin/login-details/export', { params, responseType: 'blob' }),

  parameterLimits: () => api.get('/admin/parameter-limits'),
  updateParameterLimits: (payload) => api.put('/admin/parameter-limits', payload),

  /** The admin-configured location access scope (STATE / COUNTRY / off). */
  locationScope: () => api.get('/admin/location-scope'),
  updateLocationScope: (payload) => api.put('/admin/location-scope', payload),
  /**
   * PROMPT 13: the append-only history of scope changes, newest first.
   * Refused attempts are included - a denied change is exactly what an admin
   * reviewing this list is looking for.
   */
  locationScopeAudits: (params) => api.get('/admin/location-scope/audits', { params }),
  /**
   * PROMPT 13: the states that may be chosen within a country, so the console
   * offers a choice from real resolved geography instead of free text.
   */
  locationScopeOptions: (params) => api.get('/admin/location-scope/options', { params }),

  notifications: () => api.get('/admin/notifications'),
  updateNotifications: (payload) => api.put('/admin/notifications', payload),

  models: () => api.get('/admin/models'),
  activeModel: () => api.get('/admin/models/active'),
  uploadModel: (formData) =>
    api.post('/admin/models/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  activateModel: (name) => api.post(`/admin/models/${encodeURIComponent(name)}/activate`),

  /* --------------------------------------------------------------------------
   * Model version registry.
   *
   * PROMPT 7. These sit ALONGSIDE the four methods above rather than replacing
   * them: the existing `models` / `activeModel` / `uploadModel` /
   * `activateModel` calls keep working exactly as they did, and the console uses
   * both sets. The registry is the versioned, audited, validated path; the older
   * one is still there for anything already depending on it.
   *
   * Nothing here decides whether a model is acceptable. Every call asks the
   * backend, which validates the artifact server-side in an isolated process
   * and re-checks authorisation on the way in - so a caller bypassing this module
   * gains nothing.
   * -------------------------------------------------------------------------- */

  /** The deployed project / backend / model versions and the deployment state. */
  modelVersionsStatus: () => api.get('/admin/model-versions/status'),
  /** Every registered model version, newest first. `status` optionally filters. */
  modelVersions: (params) => api.get('/admin/model-versions', { params }),
  /**
   * Register and validate an uploaded artifact. `formData` must carry the
   * `file`, a `version` string, and optionally `name`, `notes`, a `checksum`
   * the upload is expected to match, and `validate: '0'`.
   *
   * NOTE the content type: the browser must be allowed to set the multipart
   * boundary itself, so `Content-Type` is deliberately left for axios rather than
   * forced here. Forcing it is the classic multipart upload bug - the boundary
   * goes missing and the server sees a body it cannot parse.
   */
  registerModelVersion: (formData) =>
    api.post('/admin/model-versions', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  /** Re-run the isolated validation for one registered version. */
  validateModelVersion: (id) => api.post(`/admin/model-versions/${id}/validate`),
  /** Activate a version whose validation passed. */
  activateModelVersion: (id) => api.post(`/admin/model-versions/${id}/activate`),
  /** Roll the active model back to an earlier validated version. */
  rollbackModelVersion: (id) => api.post(`/admin/model-versions/${id}/rollback`),
  /** The append-only audit trail of every attempted model change. */
  modelAuditLog: (params) => api.get('/admin/model-audit-log', { params }),

  reports: (params) => api.get('/admin/reports', { params }),
  reportsSummary: (params) => api.get('/admin/reports/summary', { params }),
  /**
   * The Unsafe Prediction History: ONLY rows the model judged `unsafe`.
   *
   * The filter is applied in SQL on the backend, so this returns every unsafe
   * reading in the account's scope rather than a client-filtered page of mixed
   * rows. Supports `search` and an optional `start` / `end` day window.
   */
  unsafeHistory: (params) => api.get('/admin/unsafe-history', { params }),
  exportReports: (params) =>
    api.get('/admin/reports/export', { params, responseType: 'blob' }),

  /** Which AI providers and mail transport are configured. Presence only, no secrets. */
  providers: () => api.get('/admin/providers'),
  sendTestEmail: (email) => api.post('/admin/diagnostics/email', { email }),
}

/* -------------------------------------------------------------------------- */
/* Aqua AI                                                                     */
/* -------------------------------------------------------------------------- */
export const aiApi = {
  /**
   * Send one turn to Aqua AI and receive its reply.
   *
   * Calls the canonical `POST /api/aqua-ai/chat` (baseURL is `/api`). The
   * backend serves the same handler at `/api/ai/aqua-ai/chat` and the versioned
   * equivalent too, so the path does not move with the API version.
   *
   * The LLM provider key lives only on the backend — the browser never holds an
   * API key, and the reply contains no secret.
   */
  chat: (payload) => api.post('/aqua-ai/chat', payload),
  listConversations: () => api.get('/ai/conversations'),
  createConversation: (payload) => api.post('/ai/conversations', payload || {}),
  getConversation: (id) => api.get(`/ai/conversations/${id}`),
  deleteConversation: (id) => api.delete(`/ai/conversations/${id}`),
  /** The catalogue of controlled tools the assistant is allowed to request. */
  tools: () => api.get('/ai/tools'),
}

/** Route map re-exported so navigation logic has a single import site. */
export { ROUTES }
