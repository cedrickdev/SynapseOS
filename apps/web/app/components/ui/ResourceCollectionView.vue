<script setup lang="ts">
import type { BackendResource } from '../../../shared/backend'

const props = defineProps<{
  title: string
  description: string
  icon: string
  resource: BackendResource
}>()

const { data, status, refresh } = useBackendResource(props.resource)
</script>

<template>
  <div class="page-stack">
    <PageHeading :title="title" :description="description" :icon="icon">
      <button class="secondary-button" type="button" :disabled="status === 'pending'" @click="refresh()">
        <UIcon name="i-lucide-refresh-cw" aria-hidden="true" /> Refresh
      </button>
    </PageHeading>
    <ContractState v-if="status === 'pending'" state="loading" />
    <BackendDataView v-else-if="data?.state === 'ready'" :data="data.data" />
    <ContractState v-else-if="data?.state === 'unavailable'" state="unavailable" :message="data.message" />
    <ContractState v-else state="error" :message="data?.message" @retry="refresh()" />
  </div>
</template>
