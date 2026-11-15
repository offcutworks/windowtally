/**
 * Whether the desktop app hosts this session, which decides the account the band, the panel and the limit warnings
 * set apart: the desktop app's in a session the app hosts, the CLI's otherwise (status.ts, accountInUse).
 */

import type { EngineInterface } from 'claude-code'

/** The entrypoint the desktop app starts its sessions' engines under, the one their registry files name too. */
const DESKTOP_ENTRYPOINT = 'claude-desktop'

/**
 * Whether the desktop app hosts this session. `surfaces`, where the caller has read them already, saves reading them
 * again.
 *
 * The app starts its sessions' engines under this entrypoint, while a desktop surface is attached only as long as a
 * window shows the session: a session the app hosts may be drawn on another surface alone, such as a phone's, or on
 * none (measured 2026-11-11 under the CLI's build 2.1.310 and the desktop app's 2.1.321). Either sign is enough: the
 * entrypoint is an environment variable Claude Code does not document, so the surface still answers for a session a
 * window shows. A terminal surface outweighs both: the app's engines draw on none, while a `claude` started from a
 * shell the app's session opened inherits the app's entrypoint, Claude Code setting it only where it is unset. A `-p`
 * run such a shell starts inherits it too and draws nowhere, so it counts as the app's: its work is that session's.
 */
export async function isHostedByDesktop($: EngineInterface, surfaces?: readonly string[]): Promise<boolean> {
  const drawnOn = surfaces ?? (await $.session.surfaces())
  if (drawnOn.includes('terminal')) return false
  if (drawnOn.includes('desktop')) return true
  return (await $.env.get('CLAUDE_CODE_ENTRYPOINT')) === DESKTOP_ENTRYPOINT
}
