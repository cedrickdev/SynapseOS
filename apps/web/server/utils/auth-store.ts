import type { H3Event } from 'h3'

import type { AuthSession } from './auth-session'

export interface PendingAuthorization {
  readonly verifier: string
  readonly expiresAt: number
}

export const SESSION_COOKIE = '__Host-synapseos_session'
export const STATE_COOKIE = '__Host-synapseos_oidc_state'

const COOKIE_OPTIONS = Object.freeze({
  httpOnly: true,
  secure: true,
  sameSite: 'lax' as const,
  path: '/',
})
const MAX_AUTH_RECORDS_PER_KIND = 2_048

interface AuthStorageReader {
  getKeys(prefix: string): Promise<string[]>
  getItem<T>(key: string): Promise<T | null | undefined>
  removeItem(key: string): Promise<void>
}

interface AuthStorageWriter extends AuthStorageReader {
  setItem<T>(key: string, value: T): Promise<void>
}

let storageWriteTail: Promise<void> = Promise.resolve()

function authStorage() {
  return useStorage('auth')
}

export async function ensureAuthStorageCapacity(
  storage: AuthStorageReader,
  prefix: string,
  nowSeconds: number = Math.floor(Date.now() / 1_000),
  maxEntries: number = MAX_AUTH_RECORDS_PER_KIND,
): Promise<void> {
  const keys = await storage.getKeys(prefix)
  if (keys.length > maxEntries * 2) {
    throw new Error('Authentication session capacity is exhausted')
  }
  let liveEntries = 0
  let evictionKey: string | undefined
  let earliestExpiry = Number.POSITIVE_INFINITY
  for (const key of keys) {
    const record = await storage.getItem<{ expiresAt?: unknown }>(key)
    if (!record || typeof record.expiresAt !== 'number' || record.expiresAt <= nowSeconds) {
      await storage.removeItem(key)
    } else {
      liveEntries += 1
      if (record.expiresAt < earliestExpiry) {
        earliestExpiry = record.expiresAt
        evictionKey = key
      }
    }
  }
  if (liveEntries >= maxEntries) {
    if (!evictionKey) {
      throw new Error('Authentication session capacity is exhausted')
    }
    await storage.removeItem(evictionKey)
  }
}

async function writeBoundedRecord<T>(prefix: string, key: string, value: T): Promise<void> {
  const storage = authStorage() as AuthStorageWriter
  const operation = storageWriteTail.then(async () => {
    await ensureAuthStorageCapacity(storage, prefix)
    await storage.setItem(key, value)
  })
  storageWriteTail = operation.catch(() => undefined)
  await operation
}

export async function savePendingAuthorization(
  state: string,
  pending: PendingAuthorization,
): Promise<void> {
  await writeBoundedRecord('pending:', `pending:${state}`, pending)
}

export async function consumePendingAuthorization(
  state: string,
  nowSeconds: number = Math.floor(Date.now() / 1_000),
): Promise<PendingAuthorization | undefined> {
  const key = `pending:${state}`
  const pending = await authStorage().getItem<PendingAuthorization>(key)
  await authStorage().removeItem(key)
  if (!pending || pending.expiresAt <= nowSeconds) {
    return undefined
  }
  return pending
}

export async function saveAuthSession(event: H3Event, session: AuthSession): Promise<void> {
  await writeBoundedRecord('session:', `session:${session.id}`, session)
  setCookie(event, SESSION_COOKIE, session.id, {
    ...COOKIE_OPTIONS,
    maxAge: Math.max(1, session.expiresAt - Math.floor(Date.now() / 1_000)),
  })
}

export async function readAuthSession(event: H3Event): Promise<AuthSession | undefined> {
  const sessionId = getCookie(event, SESSION_COOKIE)
  if (!sessionId || sessionId.length > 64) {
    return undefined
  }
  const key = `session:${sessionId}`
  const session = await authStorage().getItem<AuthSession>(key)
  if (!session || session.id !== sessionId || session.expiresAt <= Math.floor(Date.now() / 1_000)) {
    await authStorage().removeItem(key)
    deleteCookie(event, SESSION_COOKIE, COOKIE_OPTIONS)
    return undefined
  }
  return session
}

export async function deleteAuthSession(event: H3Event, session: AuthSession): Promise<void> {
  await authStorage().removeItem(`session:${session.id}`)
  deleteCookie(event, SESSION_COOKIE, COOKIE_OPTIONS)
}

export function setAuthorizationStateCookie(event: H3Event, state: string): void {
  setCookie(event, STATE_COOKIE, state, { ...COOKIE_OPTIONS, maxAge: 300 })
}

export function clearAuthorizationStateCookie(event: H3Event): void {
  deleteCookie(event, STATE_COOKIE, COOKIE_OPTIONS)
}
