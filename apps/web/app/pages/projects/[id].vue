<script setup lang="ts">const route = useRoute(); const identifier = computed(() => String(route.params.id))</script>
<template><ResourceDetailView title="Project detail" description="Delivery context, gates and evidence for one project." icon="i-lucide-panel-top" resource="projects" :identifier="identifier" /></template>
