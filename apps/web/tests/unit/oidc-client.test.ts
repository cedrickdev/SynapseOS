import { describe, expect, it, vi } from 'vitest'

import {
  buildAuthorizationRequest,
  exchangeAuthorizationCode,
  isAbortError,
} from '../../server/utils/oidc-client'

const CONFIG = {
  authorizationEndpoint: 'https://auth.example/application/o/authorize/',
  tokenEndpoint: 'https://auth.example/application/o/token/',
  clientId: 'synapseos-web',
  clientSecret: 'server-only-secret',
  redirectUri: 'https://synapseos.example/api/auth/callback',
  timeoutMs: 2_000,
  maxResponseBytes: 4_096,
}

describe('OIDC authorization-code client', () => {
  it('creates a PKCE request without exposing the verifier or client secret', () => {
    const request = buildAuthorizationRequest(CONFIG)
    const url = new URL(request.location)

    expect(url.searchParams.get('state')).toBe(request.state)
    expect(url.searchParams.get('code_challenge_method')).toBe('S256')
    expect(url.searchParams.get('code_challenge')).not.toBe(request.verifier)
    expect(request.location).not.toContain(request.verifier)
    expect(request.location).not.toContain(CONFIG.clientSecret)
  })

  it('exchanges one code once and ignores provider refresh tokens', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      access_token: 'provider-access-token',
      token_type: 'Bearer',
      expires_in: 300,
      refresh_token: 'must-not-be-returned',
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))

    await expect(exchangeAuthorizationCode(
      { ...CONFIG, maxResponseBytes: 20_000 },
      'authorization-code',
      'pkce-verifier',
      fetcher,
    )).resolves.toEqual({ accessToken: 'provider-access-token', expiresInSeconds: 300 })

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(CONFIG.tokenEndpoint, expect.objectContaining({
      method: 'POST',
      redirect: 'error',
    }))
  })

  it('propagates request cancellation to the token exchange', async () => {
    const controller = new AbortController()
    controller.abort()
    const fetcher = vi.fn(async (_input: string, init: RequestInit) => {
      if (init.signal?.aborted) {
        throw new DOMException('Request cancelled', 'AbortError')
      }
      return new Response(null, { status: 500 })
    })

    await expect(exchangeAuthorizationCode(
      { ...CONFIG, maxResponseBytes: 20_000 },
      'authorization-code',
      'pkce-verifier',
      fetcher,
      controller.signal,
    )).rejects.toMatchObject({ name: 'AbortError' })

    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('identifies cancellation errors without exposing provider failures', () => {
    expect(isAbortError(new DOMException('Request cancelled', 'AbortError'))).toBe(true)
    expect(isAbortError(new Error('provider secret'))).toBe(false)
  })

  it('rejects access tokens larger than the backend verification limit', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      access_token: 'x'.repeat(16_385),
      token_type: 'Bearer',
      expires_in: 300,
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }))

    await expect(exchangeAuthorizationCode(
      { ...CONFIG, maxResponseBytes: 20_000 },
      'authorization-code',
      'pkce-verifier',
      fetcher,
    )).rejects.toThrow('OIDC token exchange failed')
  })
})
