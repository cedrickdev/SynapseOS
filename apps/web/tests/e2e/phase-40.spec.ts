import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const primaryRoutes = [
  ['/', 'Company pulse'],
  ['/projects', 'Projects'],
  ['/tasks', 'Tasks'],
  ['/agents', 'Agents'],
  ['/runs', 'Runs'],
  ['/audit', 'Audit'],
  ['/feedback', 'Feedback'],
  ['/security', 'Security findings'],
  ['/costs', 'Costs'],
  ['/settings', 'Settings']
] as const

async function gotoApp(page: import('@playwright/test').Page, path: string): Promise<void> {
  await page.goto(path)
  await expect(page.locator('#synapse-app')).toHaveAttribute('data-hydrated', 'true')
}

test('every Phase 40 screen is reachable from the application shell', async ({ page }) => {
  for (const [path, heading] of primaryRoutes) {
    await gotoApp(page, path)
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
  }
})

test('the dashboard and navigation have no automatically detectable accessibility violations', async ({ page }) => {
  await gotoApp(page, '/')
  await expect(page.getByRole('heading', { name: 'Company pulse', level: 1 })).toBeVisible()

  const results = await new AxeBuilder({ page }).analyze()
  expect(results.violations).toEqual([])
})

test('the mobile shell opens navigation and reaches a core screen', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith('mobile'), 'Mobile-only navigation check')

  await gotoApp(page, '/')
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: /Projects/ }).click()
  await expect(page.getByRole('heading', { name: 'Projects', level: 1 })).toBeVisible()
})

test('the command palette opens from its control and the global shortcut', async ({ page }) => {
  await gotoApp(page, '/')
  await page.getByRole('button', { name: 'Open command palette' }).click()
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeHidden()

  await page.keyboard.press('ControlOrMeta+K')
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: 'Search navigation' })).toBeFocused()
})
