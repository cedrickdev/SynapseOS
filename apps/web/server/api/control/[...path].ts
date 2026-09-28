import { readAuthSession } from '../../utils/auth-store'
import { buildControlBackendPath } from '../../utils/control-path'
import { requestControlBackend } from '../../utils/control-request'
import { readBoundedRequestJson } from '../../utils/request-body'
import { createRequestCancellationScope } from '../../utils/request-cancellation'

const MAX_CONTROL_REQUEST_BYTES = 20_000

export default defineEventHandler(async (event) => {
  const method = getMethod(event).toUpperCase()
  if (method !== 'GET' && method !== 'POST') {
    throw createError({ statusCode: 405, statusMessage: 'Method not allowed' })
  }
  const rawPath = getRouterParam(event, 'path') ?? ''
  let path: string
  try {
    path = buildControlBackendPath(method, rawPath.split('/').filter(Boolean))
  } catch {
    throw createError({ statusCode: 404, statusMessage: 'Resource not found' })
  }

  const session = await readAuthSession(event)
  if (!session) {
    throw createError({ statusCode: 401, statusMessage: 'Authentication required' })
  }
  let body: Record<string, unknown> | undefined
  if (method === 'POST') {
    try {
      body = await readBoundedRequestJson(event.node.req, MAX_CONTROL_REQUEST_BYTES)
    } catch {
      throw createError({ statusCode: 400, statusMessage: 'Invalid control request' })
    }
  }

  const config = useRuntimeConfig(event)
  const cancellation = createRequestCancellationScope(event.node.req, event.node.res)
  try {
    return await requestControlBackend(path, method, body, {
      baseUrl: config.backendBaseUrl,
      timeoutMs: config.backendTimeoutMs,
      maxResponseBytes: config.backendMaxResponseBytes,
      serviceToken: config.backendServiceToken,
      accessToken: session.accessToken,
      companyId: config.oidcCompanySlug,
    }, fetch, cancellation.signal)
  } finally {
    cancellation.dispose()
  }
})
