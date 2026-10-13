/**
 * Stub for the API client, used only by the render smoke-checks.
 *
 * Importing the real `@/api` drags in axios, whose `form-data` dependency calls
 * `require('util')` — which cannot be bundled as ESM for Node. That is a lot of
 * machinery to answer "does this page render", so the modules are stubbed.
 *
 * Most stubs return a never-resolving promise: the component mounts, calls its
 * loader, and renders its loading state, which is the tree we want to check.
 */

const pending = () => new Promise(() => {})

/**
 * One stored prediction, so the Reports page has a row to build a sheet from.
 *
 * The history stub below RESOLVES with this row rather than hanging. The page
 * renders an empty state until it has a row, and the report sheet — the
 * masthead, the parameter table, the identifiers — only exists once a row is
 * selected, so a never-resolving stub could never exercise it.
 */
export const SAMPLE_ROW = {
  id: 42,
  ph: 7.2,
  turbidity: 1.4,
  tds: 310,
  temperature: 19,
  dissolved_oxygen: 8.1,
  prediction: 'safe',
  confidence: 0.93,
  created_at: '2026-09-18T17:15:00',
  // Step 9: the stored location metadata a history row now carries.
  location_name: 'Karaikudi',
  location_city: 'Karaikudi',
  location_state: 'Tamil Nadu',
  location_country: 'India',
  location_pincode: '630001',
  location_lat: 10.0667,
  location_lng: 78.7833,
  water_source_type: 'ground water',
}

const sampleHistory = () =>
  Promise.resolve({ data: { data: [SAMPLE_ROW], meta: { total: 1 }}})

export const api = { get: pending, post: pending, patch: pending, delete: pending }

export const predictionApi = {
  history: sampleHistory,
  list: sampleHistory,
  predict: pending,
  getById: pending,
  stats: pending,
  latest: pending,
  remove: pending,
}

// A full prediction result, used by the Predict render smoke-check. It carries
// the exact keys the step-8 contract names - prediction, confidence, risk,
// parameters, location - so the result panel can be rendered without a model.
export const PREDICT_RESULT = {
  id: 7,
  prediction: 'moderate',
  confidence: 0.78,
  parameters: {
    ph: { label: 'pH', unit: 'pH', min: 0, max: 14, value: 7.0 },
    turbidity: { label: 'Turbidity', unit: 'NTU', min: 0, max: 1000, value: 20.0 },
    tds: { label: 'Total Dissolved Solids', unit: 'mg/L', min: 0, max: 50000, value: 900.0 },
    temperature: { label: 'Temperature', unit: '\u00b0C', min: -5, max: 100, value: 25.0 },
    dissolved_oxygen: { label: 'Dissolved Oxygen', unit: 'mg/L', min: 0, max: 20, value: 5.0 },
  },
  location_name: 'Karaikudi',
  location_state: 'Tamil Nadu',
  water_source_type: 'ground water',
  created_at: '2026-09-18T17:15:00',
}

export const alertApi = {
  list: pending,
  summary: pending,
  markRead: pending,
  markAllRead: pending,
  acknowledge: pending,
  resolve: pending,
  unresolve: pending,
}

export const dashboardApi = {
  summary: pending,
  recent: pending,
  overview: pending,
  charts: pending,
  parameters: pending,
}

export const profileApi = {
  get: pending,
  update: pending,
  changePassword: pending,
}

export const aiApi = {
  chat: pending,
  listConversations: pending,
  createConversation: pending,
  getConversation: pending,
  deleteConversation: pending,
  tools: pending,
}

export const healthApi = {
  check: pending,
  checkDatabase: pending,
}

// The location lookup surface. `context` resolves, because the Location page
// renders the identified water source and its default parameters from it and a
// never-resolving stub would only ever exercise the loading state.
export const locationApi = {
  search: () => Promise.resolve({ data: [] }),
  reverse: pending,
  parameters: pending,
  water: pending,
  context: () =>
    Promise.resolve({
      data: {
        place: { name: 'Pune', label: 'Pune, Maharashtra, India', lat: 18.52, lon: 73.85 },
        in_scope: true,
        scope_reason: null,
        water: {
          primary: 'municipal water source',
          types: ['municipal water source', 'piped water', 'rain water'],
          nearby: [],
          nearest: null,
        },
        rain: {
          status: { key: 'none', label: 'No significant rain' },
          raining_now: false,
          current_mm: 0,
          will_rain: false,
          soon_mm: 0,
          total_mm: 0,
          days: [],
          rainiest_day: null,
          alert: false,
          message: null,
        },
        risks: [{ type: 'municipal water source', risk: 'chlorine residual taste' }],
        risk_level: {
          level: 'low',
          label: 'Low',
          factors: [{ source: 'source type', detail: 'municipal water source (identified from mapped water data)' }],
          message: null,
        },
        default_parameters: {
          ph: 7.2,
          turbidity: 1.5,
          tds: 300.0,
          temperature: 25.0,
          dissolved_oxygen: 7.0,
        },
        default_parameters_detail: {
          values: {
            ph: 7.2,
            turbidity: 1.5,
            tds: 300.0,
            temperature: 25.0,
            dissolved_oxygen: 7.0,
          },
          source: 'estimated',
          label: 'Estimated',
          note: 'Typical values for municipal water source, not a measurement at this location.',
        },
      },
    }),
}

// The admin console. `sessionState` resolves as LOCKED, which is the honest
// default: the smoke check then asserts that nothing but the lock screen renders,
// which is the property that matters most about this page.
export const adminApi = {
  openSession: pending,
  lockSession: pending,
  sessionState: () =>
  Promise.resolve({ data: { unlocked: false, seconds_remaining: 0, window_minutes: 30 }}),
  changePassword: pending,
  dashboard: pending,
  users: pending,
  setUserRole: pending,
  deleteUser: pending,
  loginDetails: pending,
  loginDetailsStats: pending,
  exportLoginDetails: pending,
  parameterLimits: pending,
  updateParameterLimits: pending,
  locationScope: pending,
  updateLocationScope: pending,
  notifications: pending,
  updateNotifications: pending,
  models: pending,
  activeModel: pending,
  uploadModel: pending,
  activateModel: pending,
  reports: pending,
  reportsSummary: pending,
  exportReports: pending,
  providers: pending,
  sendTestEmail: pending,
}

export { ROUTES } from '@/utils/constants'
