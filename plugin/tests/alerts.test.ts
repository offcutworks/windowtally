/**
 * The limit warnings: a toast the first time the session's account reaches 80 % and 95 % of its 5-hour window,
 * or 70 % and 90 % of its weekly window, once across every session on the account.
 */

import { expect, test } from 'claude-code/testing'
import { ALPHA, BETA, DAY, endTurn, HOME, HOUR, iso, limitsOf, start, statusDoc, T0, world } from './world'

test('the 5-hour window warns at 80 and at 95, once each, naming the account in use', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  for (const percent of [79, 81, 85, 96, 97]) {
    w.setLimits(limitsOf(percent, 10))
    await endTurn($)
  }
  expect(w.toasts).toEqual([
    'alpha: 5-hour window at 81%, past 80%; it resets in 3h 00m.',
    'alpha: 5-hour window at 96%, past 95%; it resets in 3h 00m.',
  ])
})

test('the weekly window warns at 70 and at 90', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  for (const percent of [65, 72, 89, 91]) {
    w.setLimits(limitsOf(10, percent))
    await endTurn($)
  }
  expect(w.toasts.length).toBe(2)
  expect(w.toasts[0]).toMatch(/^alpha: weekly window at 72%, past 70%; it resets /)
  expect(w.toasts[1]).toMatch(/^alpha: weekly window at 91%, past 90%; it resets /)
})

test('a jump past both thresholds warns once, of the higher', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  w.setLimits(limitsOf(50, 10))
  await endTurn($)
  w.setLimits(limitsOf(97, 10))
  await endTurn($)
  expect(w.toasts).toEqual(['alpha: 5-hour window at 97%, past 95%; it resets in 3h 00m.'])
})

test('a new window warns afresh: its reset time moved on, or its figure fell', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc())
  await start($)
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  w.setLimits(limitsOf(5, 10, T0 + 8 * HOUR))
  await endTurn($)
  w.setLimits(limitsOf(82, 10, T0 + 8 * HOUR))
  await endTurn($)
  w.setLimits(limitsOf(78, 10, T0 + 8 * HOUR))
  await endTurn($)
  w.setLimits(limitsOf(81, 10, T0 + 8 * HOUR))
  await endTurn($)
  expect(w.toasts.map(toast => toast.split(';')[0])).toEqual([
    'alpha: 5-hour window at 85%, past 80%',
    'alpha: 5-hour window at 82%, past 80%',
    'alpha: 5-hour window at 81%, past 80%',
  ])
})

test('a threshold another session already warned of is not repeated', async ($, on) => {
  const w = world(on, {
    store: { crossings: { [ALPHA]: { five_hour: { resetsAt: T0 + 3 * HOUR, level: 80, percent: 82 } } } },
  })
  w.setStatus(statusDoc())
  await start($)
  w.setLimits(limitsOf(84, 10))
  await endTurn($)
  w.setLimits(limitsOf(95, 10))
  await endTurn($)
  expect(w.toasts).toEqual(['alpha: 5-hour window at 95%, past 95%; it resets in 3h 00m.'])
})

test('a session that draws nowhere neither warns nor uses the warning up', async ($, on) => {
  const surfaces: string[] = []
  const w = world(on, { surfaces })
  w.setStatus(statusDoc())
  await start($)
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  expect(w.toasts).toEqual([])
  surfaces.push('desktop')
  await endTurn($)
  expect(w.toasts).toEqual(['alpha: 5-hour window at 85%, past 80%; it resets in 3h 00m.'])
})

test('a session the desktop app hosts warns of the app\'s account, though only a phone draws it', async ($, on) => {
  const w = world(on, { surfaces: ['mobile'], env: { USERPROFILE: HOME, CLAUDE_CODE_ENTRYPOINT: 'claude-desktop' } })
  w.setStatus(statusDoc({ cliAccount: BETA }))
  await $.session.start({ cwd: HOME, surface: null, isInteractive: false })
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  expect(w.toasts).toEqual(['alpha: 5-hour window at 85%, past 80%; it resets in 3h 00m.'])
})

test('a terminal\'s session warns of the CLI\'s account, though it inherited the app\'s entrypoint', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'], env: { USERPROFILE: HOME, CLAUDE_CODE_ENTRYPOINT: 'claude-desktop' } })
  w.setStatus(statusDoc({ cliAccount: BETA }))
  await start($, 'terminal')
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  expect(w.toasts).toEqual(['beta: 5-hour window at 85%, past 80%; it resets in 3h 00m.'])
})

test('a warning given before the account was known is not repeated once it is', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  await start($, 'terminal')
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  w.setStatus(statusDoc(), T0 + 1)
  await w.clock.advance(15_000)
  w.setLimits(limitsOf(86, 10))
  await endTurn($)
  w.setLimits(limitsOf(96, 10))
  await endTurn($)
  expect(w.toasts.map(toast => toast.split(';')[0])).toEqual([
    '5-hour window at 85%, past 80%',
    'alpha: 5-hour window at 96%, past 95%',
  ])
})

test('a crossing another session records meanwhile is kept, not overwritten', async ($, on) => {
  const backing = new Map<string, unknown>()
  const other = { [BETA]: { seven_day: { resetsAt: T0 + 2 * DAY, level: 90, percent: 91 } } }
  let gets = 0
  on('store.get', ($, e) => {
    gets += 1
    if (gets === 2) backing.set('crossings', other)
    return { value: backing.get(e.key) }
  })
  on('store.set', ($, e) => {
    backing.set(e.key, e.value)
    return { value: undefined }
  })
  const w = world(on, { ownStore: true })
  w.setStatus(statusDoc())
  await start($)
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  expect(backing.get('crossings')).toEqual({
    ...other,
    [ALPHA]: {
      five_hour: { resetsAt: T0 + 3 * HOUR, level: 80, percent: 85 },
      seven_day: { resetsAt: T0 + 4 * DAY, level: 0, percent: 10 },
    },
  })
})

test('without a status file the warning still comes, unnamed', async ($, on) => {
  const w = world(on, { surfaces: ['terminal'] })
  await start($, 'terminal')
  w.setLimits([{ kind: 'five_hour', percentUsed: 90, resetsAt: iso(T0 + 2 * HOUR) },
               { kind: 'seven_day', percentUsed: 75, resetsAt: iso(T0 + 2 * DAY) }])
  await endTurn($)
  expect(w.toasts.length).toBe(2)
  expect(w.toasts[0]).toBe('5-hour window at 90%, past 80%; it resets in 2h 00m.')
  expect(w.toasts[1]).toMatch(/^weekly window at 75%, past 70%; it resets /)
})
