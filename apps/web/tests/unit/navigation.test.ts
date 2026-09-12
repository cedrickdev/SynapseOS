import { describe, expect, it } from 'vitest'

import { navigationSections } from '../../app/config/navigation'

describe('navigationSections', () => {
  it('keeps every Phase 40 screen reachable from the application shell', () => {
    const routes = navigationSections.flatMap(section => section.items.map(item => item.to))

    expect(routes).toEqual(expect.arrayContaining([
      '/',
      '/projects',
      '/tasks',
      '/agents',
      '/runs',
      '/audit',
      '/feedback',
      '/security',
      '/costs',
      '/settings'
    ]))
  })

  it('does not duplicate route destinations', () => {
    const routes = navigationSections.flatMap(section => section.items.map(item => item.to))

    expect(new Set(routes).size).toBe(routes.length)
  })
})
