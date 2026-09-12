<script setup lang="ts">
const shell = useShellStore(usePinia())
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">Skip to content</a>
    <AppSidebar />
    <div class="shell-workspace">
      <AppHeader />
      <main id="main-content" class="shell-main" tabindex="-1">
        <slot />
      </main>
    </div>
    <CommandPalette />
    <button
      v-if="shell.mobileNavigationOpen"
      class="mobile-scrim"
      type="button"
      aria-label="Close navigation"
      @click="shell.closeMobileNavigation()"
    />
  </div>
</template>
