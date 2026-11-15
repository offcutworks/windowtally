/**
 * An account whose bills could not all be read (status.json's subscription state `unread`, the contract stated in
 * windowtally/status_file.py): its plan line says so and points to the source problems, never that it has no bills,
 * on every surface the panel draws. Its month's sum is null, which the reader takes only in that state; elsewhere a
 * null sum is not the version-3 shape.
 */

import { expect, test } from 'claude-code/testing'
import { ALPHA, PANE, PANE_PROPS, PLUGIN, shownText, start, statusDoc, subscriptionOf, world } from './world'

const UNREAD = subscriptionOf({
  state: 'unread', plan: null, planName: null, paidUntil: null, daysLeft: null, renewSoon: false,
  thisMonthListPrice: null, profileCheck: 'unread',
})

/** The world's document with alpha's subscription as given, and `changes` to the document. */
function withAlphaSubscription(subscription: Record<string, unknown>,
                               changes: Record<string, unknown> = {}): Record<string, unknown> {
  const doc = statusDoc(changes)
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

test('an account whose bills could not all be read says so, never that it has none', async ($, on) => {
  const w = world(on)
  const problem = 'bills: _manifest.csv was not read: it has no column service_period'
  w.setStatus(withAlphaSubscription(UNREAD, {
    sourceErrors: [problem], billsUnread: true, thisMonth: { apiEquivalent: 1283.56, plansAtListPrice: null },
  }))
  await start($)
  for (const surface of ['terminal', 'desktop', 'mobile']) {
    const text = await paneText($, surface)
    expect(text).toContain('Plan  bills not all read · see Source problems below')
    expect(text).toContain(problem)
    expect(text).not.toContain('no bills recorded')
    expect(text).not.toContain('no recorded bill covers today')
    expect(text).not.toContain('paid until')
  }
})

test('a null sum this month is read only on an account whose bills were not all read', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlphaSubscription(subscriptionOf({ thisMonthListPrice: null })))
  await start($)
  expect(await paneText($, 'desktop')).toContain('not in the version-3 shape')
})
