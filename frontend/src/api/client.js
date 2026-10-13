import axios from 'axios'

import { API_BASE_URL } from '@/utils/constants'

/**
 * Shared Axios instance.
 *
 * NO TOKEN IS ATTACHED. The application is open: there is no login, so there is
 * no credential to store or send. What remains here is the transport concern -
 * one place that owns the base URL, the timeout and the error shape - so
 * components never have to inspect an Axios response object.
 *
 * Every failure is normalised into one predictable Error shape: `message`,
 * `status`, and field-level `errors`.
 */
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

/* -------------------------------------------------------------------------- */
/* Response: normalise every failure into one shape                            */
/* -------------------------------------------------------------------------- */

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const { response } = error
    const status = response?.status

    // Normalise into one shape: message, status, field-level errors.
    const message =
      response?.data?.message ||
      (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
        ? 'The request timed out. Please try again.'
        : error.request
          ? 'Cannot reach the AquaGuard AI server. Is the backend running?'
          : 'Something went wrong. Please try again.')

    const normalised = new Error(message)
    normalised.status = status
    normalised.errors = response?.data?.errors || null
    normalised.isNetworkError = !response
    // A timeout is not a network failure: the request was sent and the client
    // simply stopped waiting. The two need different wording, and the screen
    // also needs to know it may retry the SAME sample - which is safe, because
    // a request that timed out may still have been stored.
    normalised.isTimeout = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
    return Promise.reject(normalised)
  },
)

/** Convenience wrappers that resolve to `response.data`. */
export const api = {
  get: (url, config) => apiClient.get(url, config).then((r) => r.data),
  post: (url, body, config) => apiClient.post(url, body, config).then((r) => r.data),
  patch: (url, body, config) => apiClient.patch(url, body, config).then((r) => r.data),
  delete: (url, config) => apiClient.delete(url, config).then((r) => r.data),
}

export default apiClient
