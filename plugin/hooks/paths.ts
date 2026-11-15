/**
 * Where WindowTally's data folder and its files are: `~/.claude/windowtally`, the folder the ledger service owns.
 *
 * Never under AppData: a process the Claude desktop app starts, and this plugin runs inside one there, has its
 * AppData writes redirected into the app's private storage, out of the logon tasks' sight. `~/.claude` is the
 * same folder for every process.
 */

import type { EngineInterface } from 'claude-code'

export type DataPaths = {
  folder: string
  status: string
  readings: string
  /** The WindowTally window's request file: a window running takes it and shows itself (windowtally_gui/instance_model.py). */
  windowRequest: string
  separator: string
}

export async function dataPaths($: EngineInterface): Promise<DataPaths | null> {
  const home = (await $.env.get('USERPROFILE')) || (await $.env.get('HOME'))
  if (!home) return null
  const separator = home.includes('\\') ? '\\' : '/'
  const folder = [home.replace(/[\\/]+$/, ''), '.claude', 'windowtally'].join(separator)
  return {
    folder,
    status: folder + separator + 'status.json',
    readings: folder + separator + 'readings',
    windowRequest: folder + separator + 'window.request',
    separator,
  }
}

/** The session's reading file; a session id is a UUID, anything else in it is replaced. */
export function readingPath(paths: DataPaths, sessionId: string): string {
  return paths.readings + paths.separator + sessionId.replace(/[^A-Za-z0-9._-]/g, '_') + '.json'
}
