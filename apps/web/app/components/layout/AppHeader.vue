<script setup lang="ts">
const route = useRoute()
const shell = useShellStore(usePinia())
const colorMode = useColorMode()
const { locale, setLocale } = useI18n()

const pageName = computed(() => {
  const segment = route.path.split('/').filter(Boolean)[0]
  return segment ? segment.replaceAll('-', ' ') : 'dashboard'
})

function toggleTheme(): void {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}

async function toggleLocale(): Promise<void> {
  await setLocale(locale.value === 'en' ? 'fr' : 'en')
}
</script>

<template>
  <header class="app-header">
    <div class="header-context">
      <button class="icon-button menu-button" type="button" aria-label="Open navigation" @click="shell.mobileNavigationOpen = true">
        <UIcon name="i-lucide-menu" />
      </button>
      <span class="context-path"><strong>Control Center</strong><i>/</i><span>{{ pageName }}</span></span>
    </div>
    <div class="header-actions">
      <button class="command-trigger" type="button" aria-label="Open command palette" @click="shell.openCommandPalette()">
        <UIcon name="i-lucide-search" aria-hidden="true" />
        <span>Navigate</span>
        <kbd>⌘ K</kbd>
      </button>
      <button class="icon-button" type="button" :aria-label="`Switch to ${locale === 'en' ? 'French' : 'English'}`" @click="toggleLocale">
        <span class="locale-code">{{ locale.toUpperCase() }}</span>
      </button>
      <button class="icon-button" type="button" aria-label="Toggle color theme" @click="toggleTheme">
        <UIcon :name="colorMode.value === 'dark' ? 'i-lucide-sun' : 'i-lucide-moon'" />
      </button>
    </div>
  </header>
</template>
