/**
 * The panel's button that brings up the WindowTally window, a program of its own outside every Code session.
 *
 * The window runs once per user and holds its lock for its life; it looks for its request file in WindowTally's data
 * folder every half second, takes it and shows itself (windowtally_gui/instance_model.py). So a press:
 *   1. writes the request, and the window running takes it;
 *   2. with the request still there, has Task Scheduler run the window's logon task, \WindowTally\Window, through
 *      schtasks.exe: the window then lives outside the session, where a program the plugin started itself would end
 *      with the session or after ten minutes at most. The task starts the window into the tray, and the window,
 *      taking its lock, clears a request left from before it ran, so that a start into the tray shows nothing;
 *   3. once the request is gone, which says the window holds its lock, writes it again, and the window shows itself.
 * With the task not registered it says to run the installer.
 *
 * schtasks.exe is the one program the plugin runs, named by its path under the system folder, and only on a press.
 * The plugin never removes the request: `$.fs` deletes nothing, and the window clears a request at its next start.
 */

import type { EngineInterface } from 'claude-code'
import { dataPaths } from './paths'

/** The window's logon task by its qualified name: install.ps1 keeps every WindowTally task in one folder. */
export const WINDOW_TASK = '\\WindowTally\\Window'
/** How long a running window may take to see the request: it looks every half second. */
export const ASK_PATIENCE_MS = 1_500
/** How long a window the task starts may take to hold its lock, and then to show itself. */
export const START_PATIENCE_MS = 20_000
const LOOK_MS = 250
const INSTALL = 'run install.ps1 -Mode Install from the tool\'s folder'

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error))

/** Whether the file is gone within `patience` ms, looked at every LOOK_MS. */
async function goneWithin($: EngineInterface, path: string, patience: number): Promise<boolean> {
  const until = (await $.clock.now()) + patience
  for (;;) {
    if (!(await $.fs.exists(path))) return true
    if ((await $.clock.now()) >= until) return false
    await $.clock.sleep(LOOK_MS)
  }
}

/** schtasks.exe under the system folder the environment names; null where it names none (no Windows). */
async function schtasksPath($: EngineInterface): Promise<string | null> {
  const root = (await $.env.get('SystemRoot')) || (await $.env.get('SYSTEMROOT'))
  if (!root) return null
  return [root.replace(/[\\/]+$/, ''), 'System32', 'schtasks.exe'].join('\\')
}

function firstLine(text: string): string {
  return text.split(/\r?\n/).map(line => line.trim()).find(Boolean) ?? 'no reason given'
}

/** Brings up the WindowTally window, and says what came of it in a sentence. */
export async function bringUpWindow($: EngineInterface): Promise<string> {
  const where = await dataPaths($)
  if (where === null) return 'The environment names no home folder (USERPROFILE or HOME), so WindowTally cannot be found.'
  if (!(await $.fs.exists(where.folder))) return `WindowTally's data folder ${where.folder} does not exist: ${INSTALL}.`
  await $.fs.write(where.windowRequest, 'show\n')
  if (await goneWithin($, where.windowRequest, ASK_PATIENCE_MS)) return 'The window was asked to show itself.'

  const schtasks = await schtasksPath($)
  if (schtasks === null) return 'No window is running, and only Windows\' Task Scheduler can start one from here.'
  const run = await $.process.run([schtasks, '/Run', '/TN', WINDOW_TASK])
  if (run.exitCode !== 0) {
    // schtasks answers in the system's language and exits 1 for every failure, so the task's absence is told only
    // by /Query failing too, and what Task Scheduler said is passed on either way.
    const query = await $.process.run([schtasks, '/Query', '/TN', WINDOW_TASK])
    if (query.exitCode !== 0) {
      return `No window is running, and Task Scheduler cannot find its logon task ${WINDOW_TASK} ` +
        `(${firstLine(query.stderr || query.stdout)}): if it is not registered, ${INSTALL}.`
    }
    return `No window is running, and Task Scheduler did not run ${WINDOW_TASK}: ${firstLine(run.stderr || run.stdout)}`
  }
  // A window too busy to take the first request also takes this one; a second one the task started then finds the
  // window's lock held and ends, so the words below claim no start.
  if (!(await goneWithin($, where.windowRequest, START_PATIENCE_MS))) {
    return `Task Scheduler ran ${WINDOW_TASK}, but no window took the request within ${START_PATIENCE_MS / 1000} s; ` +
      `its log is window.log in ${where.folder}.`
  }
  await $.fs.write(where.windowRequest, 'show\n')
  if (await goneWithin($, where.windowRequest, START_PATIENCE_MS)) return 'The window was shown.'
  return 'The window is running; it shows itself once it is ready.'
}

/** bringUpWindow, a failure of the engine's calls said rather than thrown. */
export async function bringUpWindowSafely($: EngineInterface): Promise<string> {
  try {
    return await bringUpWindow($)
  } catch (error) {
    $.ui.log(`windowtally: the window was not brought up: ${message(error)}`, { to: 'debug' })
    return `The window was not brought up: ${message(error)}`
  }
}
