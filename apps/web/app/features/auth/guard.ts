export function authenticationRedirect(
  path: string,
  authenticated: boolean,
): string | undefined {
  if (path === '/login') {
    return authenticated ? '/' : undefined
  }
  return authenticated ? undefined : '/login'
}
