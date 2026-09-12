<script setup lang="ts">
defineProps<{
  state: 'loading' | 'unavailable' | 'error' | 'empty'
  title?: string | undefined
  message?: string | undefined
}>()

const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <section class="contract-state" :data-state="state" role="status">
    <span class="state-symbol" aria-hidden="true">
      <UIcon :name="state === 'loading' ? 'i-lucide-loader-circle' : state === 'error' ? 'i-lucide-triangle-alert' : state === 'empty' ? 'i-lucide-inbox' : 'i-lucide-plug-zap'" />
    </span>
    <div>
      <h2>{{ title ?? (state === 'loading' ? 'Loading evidence' : state === 'error' ? 'Backend unavailable' : state === 'empty' ? 'No records' : 'Contract unavailable') }}</h2>
      <p>{{ message ?? (state === 'unavailable' ? 'This screen is ready, but its backend endpoint belongs to a later implementation phase.' : 'No authoritative data is available for this surface.') }}</p>
      <button v-if="state === 'error'" class="text-button" type="button" @click="emit('retry')">Try again</button>
    </div>
  </section>
</template>
