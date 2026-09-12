<script setup lang="ts">
import { summarizeMetrics } from '../features/dashboard/metrics'

useHead({ title: 'Company pulse · SynapseOS' })

const health = useBackendResource('health')
const metrics = useBackendResource('metrics')
const metricsSummary = computed(() => metrics.data.value?.state === 'ready' ? summarizeMetrics(metrics.data.value.data) : null)
const backendHealthy = computed(() => health.data.value?.state === 'ready' && (health.data.value.data as { status?: unknown }).status === 'ok')
</script>

<template>
  <div class="page-stack dashboard-page">
    <PageHeading title="Company pulse" description="A bounded operational view of company health, evidence flow and governance readiness." icon="i-lucide-layout-dashboard">
      <span class="authority-chip"><UIcon name="i-lucide-eye" /> Supervision mode</span>
    </PageHeading>

    <section class="pulse-board" aria-labelledby="pulse-title">
      <div class="pulse-copy">
        <h2 id="pulse-title">The company is observable.<br><span>Authority stays server-side.</span></h2>
        <p>SynapseOS exposes deterministic evidence without giving the browser direct control over agents, tools, workspaces or provider credentials.</p>
        <div class="pulse-actions">
          <NuxtLink class="primary-button" to="/projects">Inspect delivery <UIcon name="i-lucide-arrow-right" /></NuxtLink>
          <NuxtLink class="secondary-button" to="/audit">Open audit trail</NuxtLink>
        </div>
      </div>
      <div class="system-orbit" aria-label="System connection status">
        <div class="orbit-ring ring-one" /><div class="orbit-ring ring-two" />
        <div class="orbit-core" :class="{ healthy: backendHealthy }">
          <UIcon name="i-lucide-network" />
          <strong>{{ backendHealthy ? 'Connected' : 'Degraded' }}</strong>
          <span>FastAPI runtime</span>
        </div>
        <span class="orbit-node node-a"><UIcon name="i-lucide-bot" /> Agents</span>
        <span class="orbit-node node-b"><UIcon name="i-lucide-shield-check" /> Security</span>
        <span class="orbit-node node-c"><UIcon name="i-lucide-git-pull-request" /> Delivery</span>
      </div>
    </section>

    <section class="signal-strip" aria-label="Runtime signals">
      <article>
        <span>Backend</span><strong><i :class="{ positive: backendHealthy }" />{{ backendHealthy ? 'Operational' : 'Unavailable' }}</strong>
      </article>
      <article>
        <span>Metric series</span><strong>{{ metricsSummary?.totalSeries ?? '—' }}</strong>
      </article>
      <article>
        <span>Governance</span><strong><UIcon name="i-lucide-lock-keyhole" /> Enforced</strong>
      </article>
      <article>
        <span>Browser authority</span><strong>Read-only</strong>
      </article>
    </section>

    <div class="dashboard-grid">
      <section class="operational-panel">
        <header><div><h2>Control Center</h2><p>Authoritative operational surfaces</p></div><NuxtLink to="/runs">View runs</NuxtLink></header>
        <div class="control-list">
          <NuxtLink to="/projects"><UIcon name="i-lucide-panels-top-left" /><span><strong>Delivery portfolio</strong><small>Projects, milestones and work gates</small></span><UIcon name="i-lucide-chevron-right" /></NuxtLink>
          <NuxtLink to="/agents"><UIcon name="i-lucide-bot" /><span><strong>Agent directory</strong><small>Availability, roles and measured history</small></span><UIcon name="i-lucide-chevron-right" /></NuxtLink>
          <NuxtLink to="/security"><UIcon name="i-lucide-shield-alert" /><span><strong>Security vetoes</strong><small>Independent findings and merge blockers</small></span><UIcon name="i-lucide-chevron-right" /></NuxtLink>
        </div>
      </section>
      <section class="operational-panel evidence-panel">
        <header><div><h2>Evidence telemetry</h2><p>Bounded aggregates, never raw prompts</p></div><span class="live-indicator"><i /> live</span></header>
        <ContractState v-if="metrics.status.value === 'pending'" state="loading" />
        <dl v-else-if="metricsSummary" class="metric-ledger">
          <div><dt>Counters</dt><dd>{{ metricsSummary.counters }}</dd></div>
          <div><dt>Histograms</dt><dd>{{ metricsSummary.histograms }}</dd></div>
          <div><dt>Gauges</dt><dd>{{ metricsSummary.gauges }}</dd></div>
        </dl>
        <ContractState v-else :state="metrics.data.value?.state === 'unavailable' ? 'unavailable' : 'error'" :message="metrics.data.value?.state !== 'ready' ? metrics.data.value?.message : undefined" @retry="metrics.refresh()" />
      </section>
    </div>
  </div>
</template>
