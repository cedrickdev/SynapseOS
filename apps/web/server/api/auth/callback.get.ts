import { createAuthSession } from '../../utils/auth-session'
import {
  clearAuthorizationStateCookie,
  consumePendingAuthorization,
  saveAuthSession,
  STATE_COOKIE,
} from '../../utils/auth-store'
import { exchangeAuthorizationCode, isAbortError } from '../../utils/oidc-client'
import { readOidcWebConfig } from '../../utils/oidc-config'
import { createRequestCancellationScope } from '../../utils/request-cancellation'

export default defineEventHandler(async (event) => {
  const query = getQuery(event)
  const code = typeof query.code === 'string' ? query.code : ''
  const state = typeof query.state === 'string' ? query.state : ''
  const stateCookie = getCookie(event, STATE_COOKIE)
  clearAuthorizationStateCookie(event)
  if (!code || !state || state !== stateCookie) {
    throw createError({ statusCode: 401, statusMessage: 'Authentication failed' })
  }
  const pending = await consumePendingAuthorization(state)
  if (!pending) {
    throw createError({ statusCode: 401, statusMessage: 'Authentication failed' })
  }
  const cancellation = createRequestCancellationScope(event.node.req, event.node.res)
  try {
    const token = await exchangeAuthorizationCode(
      readOidcWebConfig(event),
      code,
      pending.verifier,
      fetch,
      cancellation.signal,
    )
    await saveAuthSession(
      event,
      createAuthSession(token.accessToken, token.expiresInSeconds),
    )
    return sendRedirect(event, '/', 302)
  } catch (error) {
    if (cancellation.signal.aborted || isAbortError(error)) {
      throw error
    }
    throw createError({ statusCode: 502, statusMessage: 'Authentication failed' })
  } finally {
    cancellation.dispose()
  }
})
