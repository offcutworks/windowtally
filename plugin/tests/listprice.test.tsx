/**
 * The panel's plan line, which gives no cost this month, from version 3 of status.json (the contract stated in
 * windowtally/status_file.py), which still carries each plan's cost this month at its US list price, and the
 * refusal of the version before it.
 */

import { expect, test } from 'claude-code/testing'
import { ALPHA, PANE, PANE_PROPS, PLUGIN, shownText, start, statusDoc, subscriptionOf, world } from './world'

/** The world's document with alpha's subscription as given. */
function withAlphaSubscription(subscription: Record<string, unknown>): Record<string, unknown> {
  const doc = statusDoc()
  const accounts = (doc.accounts as Record<string, unknown>[]).map(account =>
    account.uuid === ALPHA ? { ...account, subscription } : account)
  return { ...doc, accounts }
}

async function paneText($: any, surface: string): Promise<string> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const text = shownText(await ui.drawn())
  await ui.unmount()
  return text
}

test('the panel gives no cost this month, at list price or paid', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  for (const surface of ['terminal', 'desktop', 'mobile']) {
    const text = await paneText($, surface)
    expect(text).toContain('Plan\u00a0\u00a0Ultra · paid until Mon 2 Nov (12d left)Updated')
    expect(text).not.toContain('$')
    expect(text).not.toContain('€')
  }
})

test('a subscription without its list-price figure is not the version-3 shape', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlphaSubscription(subscriptionOf({ thisMonthListPrice: undefined })))
  await start($)
  expect(await paneText($, 'desktop')).toContain('not in the version-3 shape')
})

test('a version-2 status file is refused, never read as version 3', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({ v: 2 }))
  await start($)
  expect(await paneText($, 'desktop')).toContain('the status file is version 2, which this plugin does not read')
})
