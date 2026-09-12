<script setup lang="ts">
import { navigationSections } from '../../config/navigation'

const route = useRoute()
const shell = useShellStore(usePinia())

function isActive(path: string): boolean {
  return path === '/' ? route.path === '/' : route.path.startsWith(path)
}
</script>

<template>
  <aside class="app-sidebar" :class="{ 'is-mobile-open': shell.mobileNavigationOpen }" aria-label="Primary">
    <div class="brand-lockup">
      <span class="brand-mark" aria-hidden="true"><span /><span /><span /></span>
      <span>
        <strong>SynapseOS</strong>
        <small>Company control plane</small>
      </span>
      <button class="icon-button sidebar-close" type="button" aria-label="Close navigation" @click="shell.closeMobileNavigation()">
        <UIcon name="i-lucide-x" />
      </button>
    </div>

    <nav class="sidebar-navigation" aria-label="Primary">
      <section v-for="section in navigationSections" :key="section.label" class="nav-section">
        <h2>{{ section.label }}</h2>
        <NuxtLink
          v-for="item in section.items"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: isActive(item.to) }"
          :aria-current="isActive(item.to) ? 'page' : undefined"
          @click="shell.closeMobileNavigation()"
        >
          <UIcon :name="item.icon" aria-hidden="true" />
          <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
        </NuxtLink>
      </section>
    </nav>

    <div class="sidebar-foot">
      <span class="live-indicator"><i aria-hidden="true" /> Governance active</span>
      <small>Browser authority: read-only</small>
    </div>
  </aside>
</template>
