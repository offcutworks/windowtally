/**
 * The band above the prompt and the panel behind it, drawn from status.json (version 3 of the contract stated
 * in windowtally/status_file.py), on every surface that draws them: the terminal in the full words, the
 * desktop with the account in use on a line of its own over the others in the compact words (plugin/hooks/band.tsx).
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BAND_PROPS, HOUR, MINUTE, PANE, PANE_PROPS, PLUGIN, STATUS, T0, shownText, start, statusDoc, subscriptionOf,
  withMoments, world,
} from './world'

const SURFACES = ['terminal', 'desktop'] as const

/**
 * Each account as each surface writes it. On the desktop the account in use stands on its own line, a group each for
 * its name, its 5-hour and its weekly window, set apart by layout rather than spaces; the others follow under a dot.
 */
const LINES = {
  terminal: {
    alpha: withMoments('alpha (app, CLI, next)  5h ≈67% ↻50m  week 69% ↻<when>'),
    beta: withMoments('beta  5h not started  week ≈96% ↻<when>'),
  },
  desktop: {
    alpha: withMoments('● alpha (app, CLI, next)5h≈67%↻50mweek69%↻<when>'),
    beta: withMoments('● beta 5h – week ≈96% ↻<when>'),
  },
} as const

async function bandText($: any, surface: string): Promise<string> {
  const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: BAND_PROPS })
  const text = shownText(await ui.drawn())
  await ui.unmount()
  return text
}

test('the band shows every account, the accounts in use first, on each surface', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  for (const surface of SURFACES) {
    const text = await bandText($, surface)
    expect(text).toMatch(LINES[surface].alpha)
    expect(text).toMatch(LINES[surface].beta)
    expect(text.indexOf('alpha')).toBeLessThan(text.indexOf('beta'))
    expect(text).toContain('[Details]')
  }
})

test('figures at or past a threshold take the warning and error colours', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'terminal', component: 'AbovePrompt', props: BAND_PROPS })
  expect((await ui.find({ type: 'Text', text: /^≈96%$/ }))?.props.color).toBe('error')
  expect(await ui.find({ type: 'Text', text: /^≈67%$/ })).toBeUndefined()
})

test('Details opens the panel, and closes it again', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'AbovePrompt', props: BAND_PROPS })
    await ui.press({ key: 'details' })
    await ui.press({ key: 'details' })
    await ui.unmount()
  }
  expect(w.opened).toEqual([PANE, PANE])
  expect(w.closed).toEqual([PANE, PANE])
})

test('a status file that is missing, not JSON, or of another version is said so', async ($, on) => {
  const w = world(on)
  await start($)
  expect(await bandText($, 'desktop')).toContain('no status file yet')
  w.setStatus('{ not json', T0 + 1)
  await w.clock.advance(15_000)
  expect(await bandText($, 'desktop')).toContain('the status file cannot be read')
  w.setStatus(statusDoc({ v: 2 }), T0 + 2)
  await w.clock.advance(15_000)
  expect(await bandText($, 'desktop')).toContain('version 2, which this plugin does not read')
  w.setStatus(statusDoc({ v: 1 }), T0 + 3)
  await w.clock.advance(15_000)
  expect(await bandText($, 'desktop')).toContain('version 1, which this plugin does not read')
})

function withAlpha(subscription: Record<string, unknown> | null, beta: Record<string, unknown> | null = null) {
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[0]!.subscription = beta
  accounts[1]!.subscription = subscription
  return doc
}

test('the band tags an account whose recorded period ends within the reminder', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlpha(subscriptionOf({ daysLeft: 2, renewSoon: true })))
  await start($)
  const renewal = { terminal: 'alpha (app, CLI, next) renew 2d  5h ≈67%', desktop: 'alpha (app, CLI, next) renew 2d5h≈67%' }
  for (const surface of SURFACES) {
    expect(await bandText($, surface)).toContain(renewal[surface])
  }
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'terminal', component: 'AbovePrompt', props: BAND_PROPS })
  expect((await ui.find({ type: 'Text', text: /^ renew 2d$/ }))?.props.color).toBe('warning')
})

test('the band shows no renewal while none is due', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  expect(await bandText($, 'desktop')).not.toContain('renew')
})

test('the panel gives each account its plan and how far it is paid up, and no cost this month', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  for (const surface of [...SURFACES, 'mobile'] as const) {
    const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'Pane', requestId: PANE, props: PANE_PROPS })
    const text = shownText(await ui.drawn())
    expect(text).toContain('Plan\u00a0\u00a0Ultra · paid until Mon 2 Nov (12d left)Updated')
    expect(text).not.toContain('at list price')
    expect(text).not.toContain('the profile names')
    await ui.unmount()
  }
})

test('the panel points out a profile naming another plan and a period that has ended', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlpha(subscriptionOf({ profilePlan: 'max5x', profileCheck: 'differs' }),
                        subscriptionOf({ state: 'ended', plan: null, planName: null, paidUntil: '2026-10-15',
                                         daysLeft: null, profilePlan: null, profileCheck: 'unknown-plan' })))
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const text = shownText(await ui.drawn())
  expect(text).toContain('· the profile names Max 5x')
  expect(text).toMatch(withMoments('● betaplan ended Thu 15 Oct · week resets ≈<when>'))
})

test('the panel names a profile on Ultra by the plan\'s name', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlpha(subscriptionOf({ plan: 'max5x', planName: 'Max 5x', profilePlan: 'ultra', profileCheck: 'differs' })))
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const text = shownText(await ui.drawn())
  expect(text).toContain('· the profile names Ultra')
  expect(text).not.toContain('no plan WindowTally compares')
})

test('a subscription that is not the version-3 shape makes the file unreadable', async ($, on) => {
  const w = world(on)
  w.setStatus(withAlpha({ state: 'active' }))
  await start($)
  expect(await bandText($, 'desktop')).toContain('one of its accounts is not in the version-3 shape')
})

test('the band follows status.json as the service rewrites it', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'AbovePrompt', props: BAND_PROPS })
  expect(shownText(await ui.drawn())).toContain('5h≈67%')
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[1]!.fiveHour = { ...accounts[1]!.fiveHour, percent: 83, estimated: false }
  w.setStatus(doc, T0 + MINUTE)
  await w.clock.advance(15_000)
  expect(shownText(await ui.drawn())).toContain('5h83%')
})

test('a stale status, source problems and every account at its limit are flagged', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({
    generatedAt: new Date(T0 - 10 * MINUTE).toISOString(),
    sourceErrors: ['transcripts: disk unreadable'],
    recommended: {
      account: null, reason: 'Every account is at its limit.', reliefAt: new Date(T0 + 2 * HOUR).toISOString(),
      reliefExact: true,
    },
  }))
  await start($)
  const text = await bandText($, 'desktop')
  expect(text).toContain('all accounts at their limit · first opens ↻2h 00m')
  expect(text).toContain('status 10m old')
  expect(text).toContain('1 source problem')
})

test('every account at or near its limit is flagged with the account it recommends', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({
    recommended: {
      account: ALPHA, reason: 'Every account is at or near its limit. alpha has the most left.',
      reliefAt: new Date(T0 + 2 * HOUR).toISOString(), reliefExact: true,
    },
  }))
  await start($)
  const text = await bandText($, 'desktop')
  expect(text).toContain('all accounts near their limit · room returns ↻2h 00m')
  expect(text).not.toContain('at their limit')
})

test('the band yields to a survey', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>survey</Text>
  })
  await start($)
  const ui = await $.ui.mount({
    plugin: PLUGIN, surface: 'terminal', component: 'AbovePrompt', props: { ...BAND_PROPS, hasSurvey: true },
  })
  expect(shownText(await ui.drawn())).toBe('survey')
})

test('the panel spells out each account, its readings and the source problems', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({ sourceErrors: ['desktop app history: version 3'], cliCondition: 'the CLI is signed out' }))
  await start($)
  for (const surface of [...SURFACES, 'mobile'] as const) {
    const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'Pane', requestId: PANE, props: PANE_PROPS })
    const text = shownText(await ui.drawn())
    expect(text).not.toContain('Desktop app:')
    expect(text).toContain('the CLI is signed out')
    expect(text).toContain('Next: alpha has room left')
    expect(text).toContain('alpha (desktop app, CLI, use next)last response 1m ago · read 2h 00m ago')
    expect(text).not.toContain('alpha@example.com')
    expect(text).toMatch(withMoments('5-hour≈67%↻50mresets ≈<when>'))
    expect(text).toMatch(withMoments('Weekly69%↻<when>in 5d 0h'))
    expect(text).not.toContain('reset time')
    expect(text).toContain('5-hournot started')
    expect(text).toContain('Source problems:')
    expect(text).toContain('desktop app history: version 3')
    await ui.unmount()
  }
})

test('a desktop app at its sign-in page is no account\'s, on the band and in the panel', async ($, on) => {
  const w = world(on)
  const doc = statusDoc({ desktopAccount: null, desktopSignedIn: false })
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[1]!.isDesktop = false
  w.setStatus(doc)
  await start($)
  const band = { terminal: 'alpha (CLI, next)  5h ≈67%', desktop: 'alpha (CLI, next) 5h ≈67%' }
  for (const surface of SURFACES) {
    const text = await bandText($, surface)
    expect(text).toContain(band[surface])
    expect(text).not.toContain('app,')
    const ui = await $.ui.mount({ plugin: PLUGIN, surface, component: 'Pane', requestId: PANE, props: PANE_PROPS })
    const panel = shownText(await ui.drawn())
    expect(panel).toContain('Desktop app: at its sign-in page.')
    expect(panel).toContain('alpha (CLI, use next)')
    await ui.unmount()
  }
})

test('the panel marks a weekly reset time ≈ only where it was inferred and no figure stands before it', async ($, on) => {
  const w = world(on)
  const doc = statusDoc()
  const accounts = doc.accounts as Array<Record<string, any>>
  accounts[1]!.weekly = { ...accounts[1]!.weekly, estimated: true }
  w.setStatus(doc)
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const text = shownText(await ui.drawn())
  expect(text).toMatch(withMoments('Weekly≈69%↻<when>in 5d 0h'))
  expect(text).toMatch(withMoments('Weekly≈96%↻<when>in 3d 4h'))   // inferred, and its figure's ≈ says so
  for (const account of accounts) account.weekly = { ...account.weekly, percent: null, estimated: false }
  w.setStatus(doc, T0 + MINUTE)
  await w.clock.advance(15_000)
  const unread = shownText(await ui.drawn())
  expect(unread).toMatch(withMoments('Weeklyunknown↻<when>in 4d 23h'))
  expect(unread).toMatch(withMoments('Weeklyunknown↻≈<when>in 3d 3h'))
})

test('the panel names the status file when it cannot be read', async ($, on) => {
  world(on)
  await start($)
  const ui = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'Pane', requestId: PANE, props: PANE_PROPS })
  const text = shownText(await ui.drawn())
  expect(text).toContain('no status file yet')
  expect(text).toContain(`Status file: ${STATUS}`)
})
