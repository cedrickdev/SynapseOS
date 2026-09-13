import { VueQueryPlugin } from '@tanstack/vue-query'

import { createDashboardQueryClient } from '../api/query-client'

export default defineNuxtPlugin((nuxtApp) => {
  nuxtApp.vueApp.use(VueQueryPlugin, {
    queryClient: createDashboardQueryClient(),
  })
})
