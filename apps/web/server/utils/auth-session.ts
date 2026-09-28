import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto'

export interface AuthSession {
  readonly id: string
  readonly accessToken: string
  readonly csrfToken: string
  readonly expiresAt: number
}

export type AuthSessionProjection = Readonly<{
  authenticated: false
} | {
  authenticated: true
  csrfToken: string
  expiresAt: number
}>

const MAX_ACCESS_TOKEN_BYTES = 16_384
const MAX_SESSION_SECONDS = 3_600

export function createAuthSession(
  accessToken: string,
  expiresInSeconds: number,
  nowSeconds: number = Math.floor(Date.now() / 1_000),
): AuthSession {
  const tokenBytes = Buffer.byteLength(accessToken, 'utf8')
  if (
    tokenBytes < 1
    || tokenBytes > MAX_ACCESS_TOKEN_BYTES
    || !Number.isSafeInteger(expiresInSeconds)
    || expiresInSeconds < 1
    || expiresInSeconds > MAX_SESSION_SECONDS
    || !Number.isSafeInteger(nowSeconds)
  ) {
    throw new Error('OIDC session input is invalid')
  }
  return Object.freeze({
    id: randomUUID(),
    accessToken,
    csrfToken: randomBytes(32).toString('base64url'),
    expiresAt: nowSeconds + expiresInSeconds,
  })
}

export function projectAuthSession(
  session: AuthSession | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1_000),
): AuthSessionProjection {
  if (!session || session.expiresAt <= nowSeconds) {
    return { authenticated: false }
  }
  return {
    authenticated: true,
    csrfToken: session.csrfToken,
    expiresAt: session.expiresAt,
  }
}

export function validateCsrfToken(
  session: AuthSession | undefined,
  candidate: string | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1_000),
): boolean {
  if (!session || session.expiresAt <= nowSeconds || !candidate) {
    return false
  }
  const expected = Buffer.from(session.csrfToken, 'utf8')
  const received = Buffer.from(candidate, 'utf8')
  return expected.length === received.length && timingSafeEqual(expected, received)
}
