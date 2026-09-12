<script setup lang="ts">
const props = defineProps<{ data: unknown }>()

const records = computed<Record<string, unknown>[]>(() => {
  if (Array.isArray(props.data)) {
    return props.data.filter((entry): entry is Record<string, unknown> => typeof entry === 'object' && entry !== null).slice(0, 100)
  }
  if (typeof props.data === 'object' && props.data !== null) {
    const object = props.data as Record<string, unknown>
    const candidate = Object.values(object).find(Array.isArray)
    if (Array.isArray(candidate)) {
      return candidate.filter((entry): entry is Record<string, unknown> => typeof entry === 'object' && entry !== null).slice(0, 100)
    }
    return [object]
  }
  return []
})

const columns = computed(() => {
  const keys = records.value.flatMap(record => Object.keys(record))
  return [...new Set(keys)].slice(0, 8)
})

function display(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 180)
  return String(value)
}
</script>

<template>
  <div v-if="records.length" class="data-table-wrap">
    <table class="data-table">
      <thead><tr><th v-for="column in columns" :key="column" scope="col">{{ column.replaceAll('_', ' ') }}</th></tr></thead>
      <tbody>
        <tr v-for="(record, index) in records" :key="String(record.id ?? index)">
          <td v-for="column in columns" :key="column" :data-label="column.replaceAll('_', ' ')">{{ display(record[column]) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <ContractState v-else state="empty" />
</template>
