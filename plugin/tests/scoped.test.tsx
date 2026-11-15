/**
 * A per-model window (Fable's): status.json gives it on the weekly window of an account that has used the model, and
 * the band, the panel and the limit warnings show it (plugin/hooks/band.tsx, panel.tsx, alerts.ts).
 */

import { expect, test } from 'claude-code/testing'
import {
  BAND_PROPS, DAY, endTurn, HOUR, iso, limitsOf, PANE, PANE_PROPS, PLUGIN, shownText, start, statusDoc, T0,
  withMoments, world,
} from './world'

/** The status, alpha's weekly window carrying Fable's at `percent`, resetting with the week unless `resetsAt` says. */
function withFable(fable: Record<string, unknown> = {}): Record<string, unknown> {
  const doc = statusDoc()
  const accounts = doc.accounts as Record<string, any>[]
  accounts[1]!.weekly.scoped = [{
    name: 'Fable', state: 'current', percent: 24.1, resetsAt: accounts[1]!.weekly.resetsAt, asOf: iso(T0 - 3 * HOUR),
    estimated: true, allowanceOfWeekly: 50, ...fable,
  }]
  return doc
}

async function drawn($: any, surface: string, component: 'AbovePrompt' | 'Pane'): Promise<string> {
  const ui = await $.ui.mount(component === 'Pane'
    ? { plugin: PLUGIN, surface, component, requestId: PANE, props: PANE_PROPS }
    : { plugin: PLUGIN, surface, component, props: BAND_PROPS })
  const text = shownText(await ui.drawn())
  await ui.unmount()
  return text
}

test('the band shows the per-model window after the weekly one, its reset being the week\'s', async ($, on) => {
  const w = world(on)
  w.setStatus(withFable())
  await start($)
  expect(await drawn($, 'terminal', 'AbovePrompt')).toMatch(withMoments('week 69% ↻<when>  Fable ≈24%'))
  expect(await drawn($, 'desktop', 'AbovePrompt')).toMatch(withMoments('week69%↻<when>Fable≈24%'))
})

test('an account without one shows none', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  expect(await drawn($, 'terminal', 'AbovePrompt')).not.toContain('Fable')
})

test('a reset of its own is said, and an unknown window says so', async ($, on) => {
  const w = world(on)
  w.setStatus(withFable({ state: 'unknown', percent: null, estimated: false, resetsAt: iso(T0 + 2 * DAY) }))
  await start($)
  expect(await drawn($, 'terminal', 'AbovePrompt')).toMatch(withMoments('Fable unknown ↻<when>'))
})

test('the panel spells it out under the weekly window', async ($, on) => {
  const w = world(on)
  w.setStatus(withFable())
  await start($)
  const text = await drawn($, 'terminal', 'Pane')
  expect(text).toContain('≈24%')
  expect(text).toContain('50% of the weekly limit')
  expect(text).toContain('read on claude.ai 3h 00m ago')
  expect(text.indexOf('Weekly')).toBeLessThan(text.indexOf('Fable'))
})

test('it warns at 80 and at 95 as a reading comes, saying what follows its allowance', async ($, on) => {
  const w = world(on)
  await start($)
  for (const percent of [70, 85, 96]) {
    w.setStatus(withFable({ percent }), T0 + percent)
    await w.clock.advance(15_000)
    w.setLimits(limitsOf(10, 30))
    await endTurn($)
  }
  expect(w.toasts.length).toBe(2)
  expect(w.toasts[0]).toMatch(/^alpha: Fable allowance at 85%, past 80%; it resets .+; past it, the model uses /)
  expect(w.toasts[0]).toMatch(/usage credits\.$/)
  expect(w.toasts[1]).toMatch(/^alpha: Fable allowance at 96%, past 95%;/)
})

test('a reading that sets the estimate a few points lower does not warn again', async ($, on) => {
  const w = world(on)
  await start($)
  for (const percent of [85, 81, 84]) {
    w.setStatus(withFable({ percent }), T0 + percent)
    await w.clock.advance(15_000)
    w.setLimits(limitsOf(10, 30))
    await endTurn($)
  }
  expect(w.toasts.filter(toast => toast.includes('Fable')).length).toBe(1)
})

test('a reset of its allowance warns afresh', async ($, on) => {
  const w = world(on)
  await start($)
  for (const percent of [85, 2, 83]) {
    w.setStatus(withFable({ percent }), T0 + percent)
    await w.clock.advance(15_000)
    w.setLimits(limitsOf(10, 30))
    await endTurn($)
  }
  expect(w.toasts.filter(toast => toast.includes('Fable')).length).toBe(2)
})
