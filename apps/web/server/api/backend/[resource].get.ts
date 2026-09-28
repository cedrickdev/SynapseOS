import { backendResources, type BackendResource } from '../../../shared/backend'
import { requestBackend } from '../../utils/backend-request'
import { readAuthSession } from '../../utils/auth-store'
import { createRequestCancellationScope } from '../../utils/request-cancellation'

export default defineEventHandler(async (event) => {
  const resource = getRouterParam(event, 'resource') ?? ''
  if (!backendResources.includes(resource as BackendResource)) {
    throw createError({ statusCode: 404, statusMessage: 'Resource not found' })
  }

  const config = useRuntimeConfig(event)
  const session = await readAuthSession(event)
  if (!session) {
    throw createError({ statusCode: 401, statusMessage: 'Authentication required' })
  }
  const cancellation = createRequestCancellationScope(event.node.req, event.node.res)
  try {
    return await requestBackend(resource, undefined, {
      baseUrl: config.backendBaseUrl,
      timeoutMs: config.backendTimeoutMs,
      maxResponseBytes: config.backendMaxResponseBytes,
      serviceToken: config.backendServiceToken,
      accessToken: session.accessToken,
      companyId: config.oidcCompanySlug,
      query: getQuery(event),
    }, fetch, cancellation.signal)
  } finally {
    cancellation.dispose()
  }
})
