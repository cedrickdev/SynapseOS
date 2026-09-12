<script setup lang="ts">
const colorMode = useColorMode()
const { locale, setLocale } = useI18n()
</script>

<template>
  <div class="page-stack">
    <PageHeading title="Settings" description="Safe browser preferences. Runtime permissions remain backend-owned." icon="i-lucide-settings-2" />
    <div class="settings-grid">
      <section class="settings-section">
        <h2>Appearance</h2><p>Choose the local cockpit presentation.</p>
        <div class="segmented-control" aria-label="Color theme">
          <button type="button" :class="{ active: colorMode.preference === 'dark' }" @click="colorMode.preference = 'dark'">Dark</button>
          <button type="button" :class="{ active: colorMode.preference === 'light' }" @click="colorMode.preference = 'light'">Light</button>
          <button type="button" :class="{ active: colorMode.preference === 'system' }" @click="colorMode.preference = 'system'">System</button>
        </div>
      </section>
      <section class="settings-section">
        <h2>Language</h2><p>Interface language is local and does not alter project records.</p>
        <div class="segmented-control" aria-label="Interface language">
          <button type="button" :class="{ active: locale === 'en' }" @click="setLocale('en')">English</button>
          <button type="button" :class="{ active: locale === 'fr' }" @click="setLocale('fr')">Français</button>
        </div>
      </section>
      <section class="settings-section safety-settings">
        <h2>Network safety</h2><p>These guarantees are enforced by the Nuxt server boundary.</p>
        <ul><li><UIcon name="i-lucide-timer" /> Mandatory request timeout</li><li><UIcon name="i-lucide-file-lock-2" /> Bounded response size</li><li><UIcon name="i-lucide-repeat-1" /> No implicit retries</li><li><UIcon name="i-lucide-eye-off" /> Sanitized upstream errors</li></ul>
      </section>
    </div>
  </div>
</template>
