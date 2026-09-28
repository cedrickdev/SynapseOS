<script setup lang="ts">
definePageMeta({ layout: false })
</script>

<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <div class="heading-icon"><UIcon name="i-lucide-shield-check" aria-hidden="true" /></div>
      <p class="eyebrow">SynapseOS Control Center</p>
      <h1 id="login-title">Sign in to supervise your agent company</h1>
      <p>Authentication is handled by your organization identity provider. Permissions remain enforced by SynapseOS.</p>
      <a class="primary-button" href="/api/auth/login">Continue with SSO</a>
    </section>
  </main>
</template>
