import { describe, expect, it } from 'vitest'

import { searchNavigation } from '../../app/features/command-palette/search'

describe('searchNavigation', () => {
  it('matches labels and descriptions case-insensitively', () => {
    expect(searchNavigation('security').map(item => item.to)).toEqual(['/security'])
    expect(searchNavigation('company DIRECTORY').map(item => item.to)).toEqual(['/agents'])
  })

  it('returns a bounded result list for an empty query', () => {
    expect(searchNavigation('', 4)).toHaveLength(4)
  })
})
