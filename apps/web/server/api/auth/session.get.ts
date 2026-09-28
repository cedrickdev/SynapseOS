import { projectAuthSession } from '../../utils/auth-session'
import { readAuthSession } from '../../utils/auth-store'

export default defineEventHandler(async (event) => {
  return projectAuthSession(await readAuthSession(event))
})
