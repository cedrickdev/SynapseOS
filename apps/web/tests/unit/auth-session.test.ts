import { describe, expect, it } from 'vitest'

import {
  createAuthSession,
  projectAuthSession,
  validateCsrfToken,
} from '../../server/utils/auth-session'
import { ensureAuthStorageCapacity } from '../../server/utils/auth-store'

describe('server-managed authentication sessions', () => {
  it('keeps the access token out of the browser-visible projection', () => {
    const session = createAuthSession('provider-access-token', 300, 1_000)

    const projection = projectAuthSession(session, 1_001)

    expect(projection).toEqual({
      authenticated: true,
      csrfToken: session.csrfToken,
      expiresAt: 1_300,
    })
    expect(JSON.stringify(projection)).not.toContain('provider-access-token')
  })

  it('rejects expired sessions and invalid CSRF tokens', () => {
    const session = createAuthSession('provider-access-token', 60, 1_000)

    expect(projectAuthSession(session, 1_060)).toEqual({ authenticated: false })
    expect(validateCsrfToken(session, 'wrong-token', 1_001)).toBe(false)
    expect(validateCsrfToken(session, session.csrfToken, 1_001)).toBe(true)
  })

  it('rejects access tokens larger than the backend verification limit', () => {
    expect(() => createAuthSession('x'.repeat(16_385), 300, 1_000)).toThrow(
      'OIDC session input is invalid',
    )
  })

  it('removes expired records and evicts the earliest live record at capacity', async () => {
    const records = new Map<string, unknown>([
      ['session:expired', { expiresAt: 999 }],
      ['session:live-a', { expiresAt: 2_000 }],
      ['session:live-b', { expiresAt: 2_000 }],
    ])
    const storage = {
      getKeys: async (prefix: string) => [...records.keys()].filter(key => key.startsWith(prefix)),
      getItem: async (key: string) => records.get(key),
      removeItem: async (key: string) => { records.delete(key) },
    }

    await expect(ensureAuthStorageCapacity(storage, 'session:', 1_000, 3)).resolves.toBeUndefined()
    expect(records.has('session:expired')).toBe(false)
    await expect(ensureAuthStorageCapacity(storage, 'session:', 1_000, 2)).resolves.toBeUndefined()
    expect(records.size).toBe(1)
  })
})
