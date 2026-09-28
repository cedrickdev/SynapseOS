import { validateCsrfToken } from '../../utils/auth-session'
import { deleteAuthSession, readAuthSession } from '../../utils/auth-store'

export default defineEventHandler(async (event) => {
  const session = await readAuthSession(event)
  const csrfToken = getHeader(event, 'x-csrf-token')
  if (!session || !validateCsrfToken(session, csrfToken)) {
    throw createError({ statusCode: 403, statusMessage: 'Request forbidden' })
  }
  await deleteAuthSession(event, session)
  return { loggedOut: true }
})
