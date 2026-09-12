<script setup lang="ts">
defineProps<{
  title: string
  description: string
  icon: string
}>()
</script>

<template>
  <header class="page-heading">
    <div class="heading-icon"><UIcon :name="icon" aria-hidden="true" /></div>
    <div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
    </div>
    <div class="heading-actions"><slot /></div>
  </header>
</template>
