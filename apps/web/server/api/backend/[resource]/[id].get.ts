import { backendResources, type BackendResource } from '../../../../shared/backend'
import { requestBackend } from '../../../utils/backend-request'

export default defineEventHandler(async (event) => {
  const resource = getRouterParam(event, 'resource') ?? ''
  const identifier = getRouterParam(event, 'id') ?? ''
  if (!backendResources.includes(resource as BackendResource)) {
    throw createError({ statusCode: 404, statusMessage: 'Resource not found' })
  }

  const config = useRuntimeConfig(event)
  return requestBackend(resource, identifier, {
    baseUrl: config.backendBaseUrl,
    timeoutMs: config.backendTimeoutMs,
    maxResponseBytes: config.backendMaxResponseBytes,
  })
})
