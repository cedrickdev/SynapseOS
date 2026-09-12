<script setup lang="ts">
const { locale } = useI18n()
const hydrated = ref(false)

useHead(() => ({
  htmlAttrs: { lang: locale.value }
}))

onMounted(() => {
  hydrated.value = true
})
</script>

<template>
  <UApp>
    <div id="synapse-app" :data-hydrated="hydrated">
      <NuxtLayout>
        <NuxtPage />
      </NuxtLayout>
    </div>
  </UApp>
</template>
