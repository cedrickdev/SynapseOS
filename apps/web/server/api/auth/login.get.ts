import { buildAuthorizationRequest } from '../../utils/oidc-client'
import { readOidcWebConfig } from '../../utils/oidc-config'
import {
  savePendingAuthorization,
  setAuthorizationStateCookie,
} from '../../utils/auth-store'

export default defineEventHandler(async (event) => {
  try {
    const request = buildAuthorizationRequest(readOidcWebConfig(event))
    await savePendingAuthorization(request.state, {
      verifier: request.verifier,
      expiresAt: Math.floor(Date.now() / 1_000) + 300,
    })
    setAuthorizationStateCookie(event, request.state)
    return sendRedirect(event, request.location, 302)
  } catch {
    throw createError({ statusCode: 503, statusMessage: 'Authentication is unavailable' })
  }
})
