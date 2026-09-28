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
  const response = await page.request.post('/api/test/session')
  expect(response.ok()).toBe(true)
  await page.goto(path)
  await expect(page.locator('#synapse-app')).toHaveAttribute('data-hydrated', 'true')
}

test('an unauthenticated application route redirects to the public login screen', async ({ page }) => {
  await page.goto('/projects')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in to supervise your agent company' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Continue with SSO' })).toHaveAttribute('href', '/api/auth/login')
})

test('every Phase 40 screen is reachable from the application shell', async ({ page }) => {
  for (const [path, heading] of primaryRoutes) {
    await gotoApp(page, path)
    await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible()
  }
})

test('the projects screen renders authoritative backend data', async ({ page }) => {
  test.skip(process.env.SYNAPSEOS_E2E_DASHBOARD !== '1', 'Requires the real dashboard API stack')

  await gotoApp(page, '/projects')
  await expect(page.getByText('Live dashboard project')).toBeVisible()
})

test('an authenticated operator can submit a bounded project intake command', async ({ page }, testInfo) => {
  const agentId = '11111111-1111-4111-8111-111111111111'
  const projectId = '22222222-2222-4222-8222-222222222222'
  const taskId = '33333333-3333-4333-8333-333333333333'
  let intakeBody: Record<string, unknown> | undefined

  await page.route('**/api/backend/agents?**', async route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      state: 'ready',
      data: {
        items: [{
          id: agentId,
          name: 'Playwright Developer',
          slug: 'playwright-developer',
          role: 'Developer',
          department: 'Engineering',
          seniority: 'ENGINEER',
          status: 'AVAILABLE',
          autonomy_level: 1,
          reputation_score: '0',
          reliability_score: '0',
          created_at: '2026-09-28T00:00:00Z',
          updated_at: '2026-09-28T00:00:00Z',
        }],
        limit: 100,
        offset: 0,
        total: 1,
      },
    }),
  }))
  await page.route('**/api/control/projects', async route => {
    intakeBody = await route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        state: 'ready',
        data: { project_id: projectId, task_id: taskId, status: 'PLANNING', replayed: false },
      }),
    })
  })

  await gotoApp(page, '/')
  if (testInfo.project.name.startsWith('mobile')) {
    await page.getByRole('button', { name: 'Open navigation' }).click()
  }
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: /Projects/ }).click()
  await page.getByRole('link', { name: 'New project' }).click()
  await page.getByLabel('Project name').fill('Playwright control project')
  await page.getByLabel('Initial task').fill('Run the bounded workflow')
  await page.getByLabel('Assigned agent').selectOption(agentId)
  await page.getByLabel('Specification').fill('Verify the authenticated operational frontend flow.')
  await page.getByRole('button', { name: 'Create project' }).click()

  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`))
  expect(intakeBody).toMatchObject({
    name: 'Playwright control project',
    task_title: 'Run the bounded workflow',
    assigned_agent_id: agentId,
  })
  expect(intakeBody?.command_id).toEqual(expect.any(String))
  expect(intakeBody?.correlation_id).toEqual(expect.any(String))
  expect(intakeBody?.idempotency_key).toEqual(expect.stringMatching(/^intake-/))
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
