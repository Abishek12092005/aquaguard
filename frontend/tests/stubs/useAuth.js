/** Stub for the auth context, used only by the Home render smoke-check. */
export function useAuth() {
  return { user: { name: 'Test User' }, isAuthenticated: true, initialising: false }
}
