import { describe, expect, it, vi } from 'vitest'

import { requestBackend } from '../../server/utils/backend-request'

describe('requestBackend', () => {
  it('performs exactly one bounded request and returns classified data', async () => {
    const fetcher = vi.fn(async () => new Response('{"status":"ok"}', {
      status: 200,
      headers: { 'content-type': 'application/json' }
    }))

    await expect(requestBackend('health', undefined, {
      baseUrl: 'http://backend:8000',
      timeoutMs: 500,
      maxResponseBytes: 128
    }, fetcher)).resolves.toEqual({ state: 'ready', data: { status: 'ok' } })

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith('http://backend:8000/health', expect.objectContaining({
      method: 'GET',
      redirect: 'error'
    }))
  })

  it('does not expose an upstream body when the request fails', async () => {
    const secret = 'internal-database-password'
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ detail: secret }), {
      status: 500,
      headers: { 'content-type': 'application/json' }
    }))

    const result = await requestBackend('projects', undefined, {
      baseUrl: 'http://backend:8000',
      timeoutMs: 500,
      maxResponseBytes: 128
    }, fetcher)

    expect(JSON.stringify(result)).not.toContain(secret)
  })
})
