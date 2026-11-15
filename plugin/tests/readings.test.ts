/**
 * The readings the plugin hands the ledger service: version 1 of the contract stated in
 * windowtally/ingest_readings.py, one file per session under WindowTally's data folder.
 */

import { expect, test } from 'claude-code/testing'
import { endTurn, FOLDER, HOUR, iso, limitsOf, MINUTE, start, T0, world } from './world'

const READING_FILE = `${FOLDER}\\readings\\session-1.json`

test('a turn that made model requests writes the session reading in the version-1 shape', async ($, on) => {
  const w = world(on)
  w.setLimits(limitsOf(26, 60, T0 + HOUR, T0 + 4 * 24 * HOUR))
  await start($)
  await endTurn($)
  expect(w.writes.map(write => write.path)).toEqual([READING_FILE])
  expect(JSON.parse(w.writes[0]!.text)).toEqual({
    v: 1,
    t: T0,
    sessionId: 'session-1',
    windows: [
      { kind: 'five_hour', percentUsed: 26, resetsAt: iso(T0 + HOUR) },
      { kind: 'seven_day', percentUsed: 60, resetsAt: iso(T0 + 4 * 24 * HOUR) },
    ],
  })
})

test('a window that moves during a turn is written at once, every window kept as reported', async ($, on) => {
  const w = world(on)
  await start($)
  await $.session.measure({
    context: { window: 1_000_000 },
    rateLimits: [
      { kind: 'five_hour', percentUsed: 41.5, resetsAt: iso(T0 + 2 * HOUR) },
      { kind: 'seven_day', percentUsed: 70 },
      { kind: 'spend_limit', percentUsed: 3 },
    ],
    changed: ['rateLimits'],
  })
  expect(JSON.parse(w.writes[0]!.text).windows).toEqual([
    { kind: 'five_hour', percentUsed: 41.5, resetsAt: iso(T0 + 2 * HOUR) },
    { kind: 'seven_day', percentUsed: 70 },
    { kind: 'spend_limit', percentUsed: 3 },
  ])
})

test('nothing is written without a reading or without a model request', async ($, on) => {
  const w = world(on)
  await start($)
  await endTurn($)
  w.setLimits(limitsOf(26, 60))
  await endTurn($, false)
  await $.session.measure({ context: { window: 1_000_000 }, rateLimits: limitsOf(26, 60), changed: ['context'] })
  expect(w.writes).toEqual([])
})

test('nothing is written while the data folder does not exist', async ($, on) => {
  const w = world(on, { dataFolder: false })
  w.setLimits(limitsOf(26, 60))
  await start($)
  await endTurn($)
  expect(w.writes).toEqual([])
})

test('the same figures are rewritten only after a minute, to renew the time of the reading', async ($, on) => {
  const w = world(on)
  w.setLimits(limitsOf(26, 60))
  await start($)
  await endTurn($)
  await $.session.measure({ context: { window: 1_000_000 }, rateLimits: limitsOf(26, 60), changed: ['rateLimits'] })
  expect(w.writes.length).toBe(1)
  await w.clock.advance(2 * MINUTE)
  await endTurn($)
  expect(w.writes.length).toBe(2)
  expect(JSON.parse(w.writes[1]!.text).t).toBe(T0 + 2 * MINUTE)
  w.setLimits(limitsOf(27, 60))
  await endTurn($)
  expect(w.writes.length).toBe(3)
})
