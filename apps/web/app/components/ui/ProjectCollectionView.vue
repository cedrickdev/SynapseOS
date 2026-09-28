<script setup lang="ts">
import { useListProjectsProjectsGet } from '../../api/generated/dashboard'

const projects = useListProjectsProjectsGet({ limit: 25, offset: 0 })
withDefaults(defineProps<{ showHeading?: boolean }>(), { showHeading: true })
</script>

<template>
  <div class="page-stack">
    <PageHeading
      v-if="showHeading"
      title="Projects"
      description="Portfolio, milestones and delivery state from the authoritative backend."
      icon="i-lucide-panels-top-left"
    >
      <button
        class="secondary-button"
        type="button"
        :disabled="projects.isFetching.value"
        @click="projects.refetch()"
      >
        <UIcon name="i-lucide-refresh-cw" aria-hidden="true" /> Refresh
      </button>
    </PageHeading>
    <ContractState v-if="projects.isPending.value" state="loading" />
    <BackendDataView v-else-if="projects.data.value" :data="projects.data.value" />
    <ContractState
      v-else
      state="error"
      message="The backend could not complete this request."
      @retry="projects.refetch()"
    />
  </div>
</template>
