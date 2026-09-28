import { describe, expect, it } from 'vitest'

import { authenticationRedirect } from '../../app/features/auth/guard'

describe('authenticationRedirect', () => {
  it('redirects unauthenticated application routes to login', () => {
    expect(authenticationRedirect('/projects', false)).toBe('/login')
  })

  it('keeps login public and returns authenticated users to the dashboard', () => {
    expect(authenticationRedirect('/login', false)).toBeUndefined()
    expect(authenticationRedirect('/login', true)).toBe('/')
    expect(authenticationRedirect('/projects', true)).toBeUndefined()
  })
})
