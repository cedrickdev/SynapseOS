import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useShellStore } from '../../app/stores/shell'

describe('useShellStore', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('opens and closes the command palette without persisting sensitive state', () => {
    const store = useShellStore()

    store.openCommandPalette()
    expect(store.commandPaletteOpen).toBe(true)
    store.closeCommandPalette()
    expect(store.commandPaletteOpen).toBe(false)
  })

  it('closes the mobile navigation after route selection', () => {
    const store = useShellStore()

    store.mobileNavigationOpen = true
    store.closeMobileNavigation()
    expect(store.mobileNavigationOpen).toBe(false)
  })
})
