/**
 * The panel's button that brings up the WindowTally window, the silence the user can set on WindowTally's notifications, and
 * the ≈ the moment the first account opens again takes where it was inferred. The window itself is stood in for: it
 * takes the request file in the data folder, as windowtally_gui/instance_model.py does, and Task Scheduler is a
 * hook beneath `$.process.run`.
 */

import { expect, test } from 'claude-code/testing'
import {
  ALPHA, BAND_PROPS, FOLDER, HOME, HOUR, MINUTE, PANE, PANE_PROPS, PLUGIN, T0, endTurn, iso, limitsOf, shownText, start,
  statusDoc, world,
} from './world'

const REQUEST = `${FOLDER}\\window.request`
const SCHTASKS = 'C:\\Windows\\System32\\schtasks.exe'
const ENV = { USERPROFILE: HOME, SystemRoot: 'C:\\Windows' }

type Run = { argv: readonly string[] }
type Answer = { exitCode: number; stdout?: string; stderr?: string }

/** Task Scheduler as the test sets it: each command's answer, and every command run. */
function scheduler(on: any, answer: (argv: readonly string[]) => Answer): Run[] {
  const runs: Run[] = []
  on('process.run', ($: any, e: any) => {
    runs.push({ argv: [...e.argv] })
    const { exitCode, stdout = '', stderr = '' } = answer(e.argv)
    return { value: { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return runs
}

async function mountPanel($: any, surface = 'desktop'): Promise<any> {
  return $.ui.mount({ plugin: PLUGIN, surface, component: 'Pane', requestId: PANE, props: PANE_PROPS })
}

/**
 * Presses the button, then moves the clock on in quarter seconds, letting `step` act before each one, until the
 * panel no longer says the press is being carried out: the press resolves while its work sleeps on the clock.
 */
async function pressAndRun(ui: any, w: any, step: (elapsed: number) => void, limitMs = 60_000): Promise<void> {
  await ui.press({ key: 'window' })
  for (let elapsed = 0; elapsed <= limitMs; elapsed += 250) {
    if (!shownText(await ui.drawn()).includes('Bringing up the window…')) return
    step(elapsed)
    await w.clock.advance(250)
  }
  throw new Error(`the press did not end within ${limitMs} ms`)
}

test('the panel carries at its head a button that brings up the WindowTally window, on each surface', async ($, on) => {
  const w = world(on, { env: ENV })
  w.setStatus(statusDoc())
  await start($)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await mountPanel($, surface)
    const drawn = (await ui.drawn()) as any
    const head = drawn.children.find((child: unknown) => typeof child === 'object' && child !== null) as any
    expect(head.props.flexDirection).toBe('row')
    expect(head.children[0].type).toBe('Button')
    expect(head.children[0].props.label).toBe('Open WindowTally')
    await ui.unmount()
  }
})

test('the head stands even where status.json gives no standings', async ($, on) => {
  const w = world(on, { env: ENV })
  await start($)
  const ui = await mountPanel($)
  const text = shownText(await ui.drawn())
  expect(text).toContain('[Open WindowTally]')
  expect(text).toContain('no status file yet')
})

test('a running window is asked through its request file, and no program is run', async ($, on) => {
  const w = world(on, { env: ENV })
  const runs = scheduler(on, () => ({ exitCode: 0 }))
  w.setStatus(statusDoc())
  await start($)
  const ui = await mountPanel($)
  await pressAndRun(ui, w, elapsed => {
    if (elapsed === 500) w.files.delete(REQUEST)
  })
  expect(w.writes.filter(write => write.path === REQUEST).map(write => write.text)).toEqual(['show\n'])
  expect(runs).toEqual([])
  expect(shownText(await ui.drawn())).toContain('The window was asked to show itself.')
})

test('with no window running, Task Scheduler runs its logon task and the window is asked again once it holds its lock',
  async ($, on) => {
    const w = world(on, { env: ENV })
    let startedAt: number | null = null
    const runs = scheduler(on, argv => {
      if (argv[1] === '/Run') startedAt = 0
      return { exitCode: 0 }
    })
    w.setStatus(statusDoc())
    await start($)
    const ui = await mountPanel($)
    let asked = 0
    await pressAndRun(ui, w, () => {
      if (startedAt === null) return
      startedAt += 250
      // The window takes its lock after two seconds and clears the request left from before it ran; once ready,
      // it takes the next request and shows itself.
      if (startedAt === 2000 || (startedAt > 3000 && w.files.has(REQUEST))) {
        if (w.files.delete(REQUEST)) asked += 1
      }
    })
    expect(runs.map(run => run.argv)).toEqual([[SCHTASKS, '/Run', '/TN', '\\WindowTally\\Window']])
    expect(w.writes.filter(write => write.path === REQUEST).length).toBe(2)
    expect(asked).toBe(2)
    expect(shownText(await ui.drawn())).toContain('The window was shown.')
  })

test('a press while one is being carried out is ignored', async ($, on) => {
  const w = world(on, { env: ENV })
  scheduler(on, () => ({ exitCode: 0 }))
  w.setStatus(statusDoc())
  await start($)
  const ui = await mountPanel($)
  await ui.press({ key: 'window' })
  await ui.press({ key: 'window' })
  await pressAndRun(ui, w, elapsed => {
    if (elapsed === 500) w.files.delete(REQUEST)
  })
  expect(w.writes.filter(write => write.path === REQUEST).length).toBe(1)
})

test('with the logon task not registered, the panel says to run the installer', async ($, on) => {
  const w = world(on, { env: ENV })
  const runs = scheduler(on, () => ({ exitCode: 1, stderr: 'ERROR: The system cannot find the file specified.\r\n' }))
  w.setStatus(statusDoc())
  await start($)
  const ui = await mountPanel($)
  await pressAndRun(ui, w, () => {})
  expect(runs.map(run => run.argv[1])).toEqual(['/Run', '/Query'])
  const text = shownText(await ui.drawn())
  expect(text).toContain('Task Scheduler cannot find its logon task \\WindowTally\\Window ' +
    '(ERROR: The system cannot find the file specified.): if it is not registered')
  expect(text).toContain('install.ps1 -Mode Install')
})

test('a task that is registered but does not run is said with what Task Scheduler answered', async ($, on) => {
  const w = world(on, { env: ENV })
  scheduler(on, argv => (argv[1] === '/Run' ? { exitCode: 1, stderr: 'ERROR: Access is denied.\r\n' } : { exitCode: 0 }))
  w.setStatus(statusDoc())
  await start($)
  const ui = await mountPanel($)
  await pressAndRun(ui, w, () => {})
  expect(shownText(await ui.drawn())).toContain('Task Scheduler did not run \\WindowTally\\Window: ERROR: Access is denied.')
})

test('a window the task does not start in time is said, with where its log is', async ($, on) => {
  const w = world(on, { env: ENV })
  scheduler(on, () => ({ exitCode: 0 }))
  w.setStatus(statusDoc())
  await start($)
  const ui = await mountPanel($)
  await pressAndRun(ui, w, () => {})
  const text = shownText(await ui.drawn())
  expect(text).toContain('no window took the request within 20 s')
  expect(text).toContain(`window.log in ${FOLDER}`)
})

test('with no data folder nothing is written or run', async ($, on) => {
  const w = world(on, { env: ENV, dataFolder: false })
  const runs = scheduler(on, () => ({ exitCode: 0 }))
  await start($)
  const ui = await mountPanel($)
  await pressAndRun(ui, w, () => {})
  expect(w.writes).toEqual([])
  expect(runs).toEqual([])
  expect(shownText(await ui.drawn())).toContain(`WindowTally's data folder ${FOLDER} does not exist`)
})

test('while the notifications are silenced no limit toast is raised, and the crossing is not warned of later',
  async ($, on) => {
    const w = world(on)
    w.setStatus(statusDoc({ notificationsSilenced: true }))
    await start($)
    w.setLimits(limitsOf(85, 10))
    await endTurn($)
    expect(w.toasts).toEqual([])
    w.setStatus(statusDoc({ notificationsSilenced: false }), T0 + 1)
    await w.clock.advance(15_000)
    w.setLimits(limitsOf(86, 10))
    await endTurn($)
    expect(w.toasts).toEqual([])
    w.setLimits(limitsOf(96, 10))
    await endTurn($)
    expect(w.toasts.length).toBe(1)
    expect(w.toasts[0]).toMatch(/^alpha: 5-hour window at 96%, past 95%/)
  })

test('a status file that cannot be read for a moment leaves the silence as it stood', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({ notificationsSilenced: true }))
  await start($)
  w.setStatus('{ half written', T0 + 1)
  await w.clock.advance(15_000)
  w.setLimits(limitsOf(85, 10))
  await endTurn($)
  expect(w.toasts).toEqual([])
})

/** The reason's moment as the service writes it, ≈ where it was inferred: the panel shows the reason as it stands. */
const OPENS = 'Wed 02:10'

function allBlocked(reliefExact?: boolean): Record<string, unknown> {
  const recommended: Record<string, unknown> = {
    account: null, reason: `Every account is at its limit. The first opens ${reliefExact ? '' : '≈'}${OPENS}.`,
    reliefAt: iso(T0 + 2 * HOUR),
  }
  if (reliefExact !== undefined) recommended.reliefExact = reliefExact
  return statusDoc({ generatedAt: iso(T0 - MINUTE), recommended })
}

test('the moment the first account opens is marked ≈ only where it was inferred, on the band and in the panel',
  async ($, on) => {
    const w = world(on)
    w.setStatus(allBlocked())
    await start($)
    for (const [reliefExact, mark] of [[true, ''], [false, '≈'], [undefined, '≈']] as const) {
      w.setStatus(allBlocked(reliefExact), w.clock.now() + 1)
      await w.clock.advance(15_000)
      const opens = 2 * HOUR - (w.clock.now() - T0)
      const left = `${Math.floor(opens / HOUR)}h ${String(Math.floor((opens % HOUR) / MINUTE)).padStart(2, '0')}m`
      const band = await $.ui.mount({ plugin: PLUGIN, surface: 'desktop', component: 'AbovePrompt', props: BAND_PROPS })
      expect(shownText(await band.drawn())).toContain(`all accounts at their limit · first opens ↻${mark}${left}`)
      await band.unmount()
      const ui = await mountPanel($)
      expect(shownText(await ui.drawn())).toContain(`The first opens ${mark}${OPENS} (in ${mark}${left}).`)
      await ui.unmount()
    }
  })

test('with an account still recommended the panel says when room returns, not that one opens', async ($, on) => {
  const w = world(on)
  w.setStatus(statusDoc({
    generatedAt: iso(T0 - MINUTE),
    recommended: {
      account: ALPHA, reason: `Every account is at or near its limit. alpha has the most left. Room returns ${OPENS}.`,
      reliefAt: iso(T0 + 2 * HOUR), reliefExact: true,
    },
  }))
  await start($)
  const ui = await mountPanel($)
  const text = shownText(await ui.drawn())
  expect(text).toContain(`Next: Every account is at or near its limit. alpha has the most left. Room returns ${OPENS} (in 2h 00m).`)
  expect(text).not.toContain('The first opens')
  await ui.unmount()
})
