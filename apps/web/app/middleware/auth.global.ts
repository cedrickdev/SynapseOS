import { authenticationRedirect } from '../features/auth/guard'

interface SessionProjection {
  readonly authenticated: boolean
}

export default defineNuxtRouteMiddleware(async (to) => {
  let authenticated: boolean
  try {
    const request = import.meta.server ? useRequestFetch() : $fetch
    const session = await request<SessionProjection>('/api/auth/session', {
      retry: 0,
      timeout: 8_000,
    })
    authenticated = session.authenticated
  } catch {
    authenticated = false
  }
  const redirect = authenticationRedirect(to.path, authenticated)
  return redirect ? navigateTo(redirect) : undefined
})
