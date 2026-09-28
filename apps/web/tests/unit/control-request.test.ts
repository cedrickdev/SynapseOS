import { describe, expect, it, vi } from 'vitest'

import { requestControlBackend } from '../../server/utils/control-request'

const config = {
  baseUrl: 'http://backend:8000',
  timeoutMs: 500,
  maxResponseBytes: 512,
  serviceToken: 'private-service-token',
  accessToken: 'private-access-token',
  companyId: 'acme',
}

describe('requestControlBackend', () => {
  it('performs exactly one bounded authenticated request', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ result: 'ACCEPTED' }), {
      status: 202,
      headers: { 'content-type': 'application/json' },
    }))
    const body = { command_id: '123e4567-e89b-12d3-a456-426614174000' }

    await expect(requestControlBackend('/control/projects', 'POST', body, config, fetcher))
      .resolves.toEqual({ state: 'ready', data: { result: 'ACCEPTED' } })

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith('http://backend:8000/control/projects', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(body),
      redirect: 'error',
      headers: {
        accept: 'application/json',
        authorization: 'Bearer private-access-token',
        'content-type': 'application/json',
        'x-synapseos-company-id': 'acme',
        'x-synapseos-service-token': 'private-service-token',
      },
    }))
  })

  it('returns an actionable safe error without forwarding upstream details', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      detail: { message: 'database-password', stack: 'private-stack' },
    }), {
      status: 409,
      headers: { 'content-type': 'application/json' },
    }))

    const result = await requestControlBackend('/control/projects', 'POST', {}, config, fetcher)

    expect(result).toEqual({
      state: 'error',
      message: 'The project changed. Refresh its status before trying again.',
    })
    expect(JSON.stringify(result)).not.toContain('database-password')
  })

  it('propagates cancellation without retrying', async () => {
    const cancellation = new DOMException('cancelled', 'AbortError')
    const controller = new AbortController()
    controller.abort()
    const fetcher = vi.fn(async () => { throw cancellation })

    await expect(requestControlBackend(
      '/control/projects', 'POST', {}, config, fetcher, controller.signal,
    )).rejects.toBe(cancellation)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
