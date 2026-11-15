/**
 * A desktop app the status reports not running (status.json's `desktopRunning`, written only as false; the contract
 * stated in windowtally/status_file.py), as PROJECT.md has the band and the panel say it: the
 * terminal band's `app` tag reads `app closed`, the panel's head says the app is not running and
 * that the WindowTally window starts it, and the panel's tag reads `desktop app, not running`. A session the app hosts runs
 * inside the app, so it never reads the app not running.
 */

import { expect, test } from 'claude-code/testing'
import { BAND_PROPS, PANE, PANE_PROPS, PLUGIN, shownText, start, statusDoc, world } from './world'

const HEAD = 'The desktop app is not running; start it from the WindowTally window.'

async function drawn($: any, surface: string, component: 'AbovePrompt' | 'Pane'): Promise<string> {
  const ui = component === 'Pane'
    ? await $.ui.mount({ plugin: PLUGIN, surface, component, requestId: PANE, props: PANE_PROPS })
    : await $.ui.mount({ plugin: PLUGIN, surface, component, props: BAND_PROPS })
  const shown = shownText(await ui.drawn())
  await ui.unmount()
  return shown
}

test('the terminal band tags the desktop app\'s account app closed while the app is not running', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  w.setStatus(statusDoc({ desktopRunning: false }))
  await start($, 'terminal')
  const band = await drawn($, 'terminal', 'AbovePrompt')
  expect(band).toContain('alpha (app closed, CLI, next)')
  expect(band).not.toContain('(app, CLI')
})

test('the panel says the app is not running, that the WindowTally window starts it, and tags its account so', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  w.setStatus(statusDoc({ desktopRunning: false }))
  await start($, 'terminal')
  const panel = await drawn($, 'terminal', 'Pane')
  expect(panel).toContain(`${HEAD}Next:`)
  expect(panel).toContain('alpha (desktop app, not running, CLI, use next)')
})

test('an app at its sign-in page and not running is said both ways in the panel\'s head', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  const doc = statusDoc({ desktopAccount: null, desktopSignedIn: false, desktopRunning: false })
  for (const account of doc.accounts as Array<Record<string, unknown>>) account.isDesktop = false
  w.setStatus(doc)
  await start($, 'terminal')
  expect(await drawn($, 'terminal', 'Pane')).toContain(`Desktop app: at its sign-in page. ${HEAD}Next:`)
})

test('a session the desktop app hosts never reads the app not running, on the band or in the panel', async ($, on) => {
  const w = world(on, { surfaces: ['desktop'] })
  w.setStatus(statusDoc({ desktopRunning: false }))
  await start($)
  const band = await drawn($, 'desktop', 'AbovePrompt')
  expect(band).toContain('alpha (app, CLI, next)')
  expect(band).not.toContain('closed')
  const panel = await drawn($, 'desktop', 'Pane')
  expect(panel).not.toContain('not running')
  expect(panel).toContain('alpha (desktop app, CLI, use next)')
})

test('a status without the key says nothing of it: the app runs, or whether it runs is not known', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  w.setStatus(statusDoc())
  await start($, 'terminal')
  expect(await drawn($, 'terminal', 'AbovePrompt')).toContain('alpha (app, CLI, next)')
  expect(await drawn($, 'terminal', 'Pane')).not.toContain('not running')
})
