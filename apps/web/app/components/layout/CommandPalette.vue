<script setup lang="ts">
import { searchNavigation } from '../../features/command-palette/search'

const shell = useShellStore(usePinia())
const query = ref('')
const selectedIndex = ref(0)
const input = ref<HTMLInputElement | null>(null)
const results = computed(() => searchNavigation(query.value))

watch(() => shell.commandPaletteOpen, async (open) => {
  if (!open) return
  query.value = ''
  selectedIndex.value = 0
  await nextTick()
  input.value?.focus()
})

watch(query, () => {
  selectedIndex.value = 0
})

function close(): void {
  shell.closeCommandPalette()
}

async function selectCurrent(): Promise<void> {
  const selected = results.value[selectedIndex.value]
  if (!selected) return
  close()
  await navigateTo(selected.to)
}

function onPaletteKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    selectedIndex.value = Math.min(selectedIndex.value + 1, results.value.length - 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    void selectCurrent()
  }
}

function onGlobalKeydown(event: KeyboardEvent): void {
  if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase('en-US') === 'k') {
    event.preventDefault()
    shell.openCommandPalette()
  } else if (event.key === 'Escape' && shell.commandPaletteOpen) {
    close()
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))
</script>

<template>
  <div v-if="shell.commandPaletteOpen" class="palette-overlay" @mousedown.self="close">
    <section class="command-palette" role="dialog" aria-modal="true" aria-label="Command palette">
      <label class="palette-search">
        <UIcon name="i-lucide-search" aria-hidden="true" />
        <span class="sr-only">Search navigation</span>
        <input ref="input" v-model="query" type="search" role="searchbox" aria-label="Search navigation" placeholder="Jump to a SynapseOS surface…" @keydown="onPaletteKeydown">
        <kbd>Esc</kbd>
      </label>
      <p class="palette-hint">Navigate across Company View, Control Center and Deep Inspect.</p>
      <ul class="palette-results" role="listbox" aria-label="Navigation results">
        <li v-for="(item, index) in results" :key="item.to">
          <button type="button" :class="{ selected: selectedIndex === index }" @mousemove="selectedIndex = index" @click="selectedIndex = index; selectCurrent()">
            <UIcon :name="item.icon" aria-hidden="true" />
            <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
            <UIcon name="i-lucide-arrow-up-right" aria-hidden="true" />
          </button>
        </li>
      </ul>
      <p v-if="results.length === 0" class="palette-empty">No matching destination.</p>
    </section>
  </div>
</template>
