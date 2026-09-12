import { defineStore } from 'pinia'

export const useShellStore = defineStore('shell', {
  state: () => ({
    commandPaletteOpen: false,
    mobileNavigationOpen: false,
  }),
  actions: {
    openCommandPalette(): void {
      this.commandPaletteOpen = true
    },
    closeCommandPalette(): void {
      this.commandPaletteOpen = false
    },
    closeMobileNavigation(): void {
      this.mobileNavigationOpen = false
    },
  },
})
