import type { H3Event } from 'h3'

import type { OidcWebConfig } from './oidc-client'

export function readOidcWebConfig(event: H3Event): OidcWebConfig {
  const config = useRuntimeConfig(event)
  return {
    authorizationEndpoint: config.oidcAuthorizationEndpoint,
    tokenEndpoint: config.oidcTokenEndpoint,
    clientId: config.oidcClientId,
    clientSecret: config.oidcClientSecret,
    redirectUri: config.oidcRedirectUri,
    timeoutMs: config.oidcTimeoutMs,
    maxResponseBytes: config.oidcMaxResponseBytes,
  }
}
