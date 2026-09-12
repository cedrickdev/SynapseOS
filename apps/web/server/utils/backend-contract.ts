import type { BackendEnvelope } from '../../shared/backend'

export function classifyBackendResponse(status: number, payload: unknown): BackendEnvelope {
  if (status >= 200 && status < 300) {
    return { state: 'ready', data: payload }
  }

  if (status === 404 || status === 405 || status === 501) {
    return {
      state: 'unavailable',
      message: 'This backend contract is not available yet.',
    }
  }

  return {
    state: 'error',
    message: 'The backend could not complete this request.',
  }
}
