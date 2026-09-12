export default defineNuxtConfig({
  compatibilityDate: '2026-09-10',
  devtools: { enabled: false },
  colorMode: {
    preference: 'dark',
    fallback: 'dark'
  },
  modules: ['@nuxt/ui', '@nuxtjs/i18n', '@pinia/nuxt', '@vueuse/nuxt', '@nuxt/eslint'],
  ui: {
    fonts: false
  },
  components: [
    {
      path: '~/components',
      pathPrefix: false
    }
  ],
  css: ['~/assets/css/main.css'],
  typescript: {
    strict: true,
    typeCheck: true,
    tsConfig: {
      compilerOptions: {
        exactOptionalPropertyTypes: true,
        noUncheckedIndexedAccess: true
      }
    }
  },
  runtimeConfig: {
    backendBaseUrl: 'http://localhost:8000',
    backendTimeoutMs: 8_000,
    backendMaxResponseBytes: 1_048_576,
    public: {
      appName: 'SynapseOS'
    }
  },
  i18n: {
    defaultLocale: 'en',
    strategy: 'no_prefix',
    langDir: 'locales',
    locales: [
      { code: 'en', language: 'en-US', file: 'en.json', name: 'English' },
      { code: 'fr', language: 'fr-FR', file: 'fr.json', name: 'Français' }
    ]
  },
  routeRules: {
    '/**': {
      headers: {
        'content-security-policy': "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'",
        'referrer-policy': 'strict-origin-when-cross-origin',
        'x-content-type-options': 'nosniff',
        'x-frame-options': 'DENY',
        'permissions-policy': 'camera=(), microphone=(), geolocation=()'
      }
    }
  }
})
