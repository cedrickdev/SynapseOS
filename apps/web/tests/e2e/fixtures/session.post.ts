import { createAuthSession } from '../../../server/utils/auth-session'
import { saveAuthSession } from '../../../server/utils/auth-store'

export default defineEventHandler(async (event) => {
  const session = createAuthSession('playwright-access-token', 300)
  await saveAuthSession(event, session)
  return { authenticated: true }
})
