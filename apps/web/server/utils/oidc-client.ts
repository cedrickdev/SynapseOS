import { createHash, randomBytes } from 'node:crypto'

import { readBoundedJson } from './backend-response'

export interface OidcWebConfig {
  readonly authorizationEndpoint: string
  readonly tokenEndpoint: string
  readonly clientId: string
  readonly clientSecret: string
  readonly redirectUri: string
  readonly timeoutMs: number
  readonly maxResponseBytes: number
}

export interface AuthorizationRequest {
  readonly location: string
  readonly state: string
  readonly verifier: string
}

export interface ExchangedAccessToken {
  readonly accessToken: string
  readonly expiresInSeconds: number
}

type Fetcher = (input: string, init: RequestInit) => Promise<Response>

export function isAbortError(error: unknown): error is Error {
  return error instanceof Error && error.name === 'AbortError'
}

function requireHttpsUrl(value: string): URL {
  const parsed = new URL(value)
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('OIDC web configuration is invalid')
  }
  return parsed
}

function validateConfig(config: OidcWebConfig): void {
  requireHttpsUrl(config.authorizationEndpoint)
  requireHttpsUrl(config.tokenEndpoint)
  requireHttpsUrl(config.redirectUri)
  if (
    !config.clientId
    || !config.clientSecret
    || !Number.isSafeInteger(config.timeoutMs)
    || config.timeoutMs < 1
    || config.timeoutMs > 30_000
    || !Number.isSafeInteger(config.maxResponseBytes)
    || config.maxResponseBytes < 1_024
    || config.maxResponseBytes > 1_048_576
  ) {
    throw new Error('OIDC web configuration is invalid')
  }
}

export function buildAuthorizationRequest(config: OidcWebConfig): AuthorizationRequest {
  validateConfig(config)
  const state = randomBytes(32).toString('base64url')
  const verifier = randomBytes(32).toString('base64url')
  const challenge = createHash('sha256').update(verifier, 'ascii').digest('base64url')
  const location = requireHttpsUrl(config.authorizationEndpoint)
  location.searchParams.set('response_type', 'code')
  location.searchParams.set('client_id', config.clientId)
  location.searchParams.set('redirect_uri', config.redirectUri)
  location.searchParams.set('scope', 'openid profile email')
  location.searchParams.set('state', state)
  location.searchParams.set('code_challenge', challenge)
  location.searchParams.set('code_challenge_method', 'S256')
  return { location: location.toString(), state, verifier }
}

export async function exchangeAuthorizationCode(
  config: OidcWebConfig,
  code: string,
  verifier: string,
  fetcher: Fetcher = fetch,
  cancellationSignal?: AbortSignal,
): Promise<ExchangedAccessToken> {
  validateConfig(config)
  if (!code || code.length > 4_096 || !verifier || verifier.length > 128) {
    throw new Error('OIDC authorization response is invalid')
  }
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: config.redirectUri,
    client_id: config.clientId,
    client_secret: config.clientSecret,
    code_verifier: verifier,
  })
  try {
    const timeoutSignal = AbortSignal.timeout(config.timeoutMs)
    const signal = cancellationSignal
      ? AbortSignal.any([cancellationSignal, timeoutSignal])
      : timeoutSignal
    const response = await fetcher(config.tokenEndpoint, {
      method: 'POST',
      headers: {
        accept: 'application/json',
        'content-type': 'application/x-www-form-urlencoded',
      },
      body,
      redirect: 'error',
      signal,
    })
    if (response.status < 200 || response.status >= 300) {
      throw new Error('OIDC token exchange failed')
    }
    const payload = await readBoundedJson(response, config.maxResponseBytes)
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('OIDC token exchange failed')
    }
    const token = Reflect.get(payload, 'access_token')
    const tokenType = Reflect.get(payload, 'token_type')
    const expiresIn = Reflect.get(payload, 'expires_in')
    if (
      typeof token !== 'string'
      || Buffer.byteLength(token, 'utf8') < 1
      || Buffer.byteLength(token, 'utf8') > 16_384
      || tokenType !== 'Bearer'
      || !Number.isSafeInteger(expiresIn)
      || expiresIn < 1
      || expiresIn > 3_600
    ) {
      throw new Error('OIDC token exchange failed')
    }
    return { accessToken: token, expiresInSeconds: expiresIn }
  } catch (error) {
    if (isAbortError(error) || cancellationSignal?.aborted) {
      throw error
    }
    // Provider failures may contain credentials, so the public error intentionally has no cause.
    // eslint-disable-next-line preserve-caught-error
    throw new Error('OIDC token exchange failed')
  }
}
