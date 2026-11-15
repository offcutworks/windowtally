/**
 * How times and figures read on the band, the panel and the toasts.
 *
 * Wall-clock times are drawn in the time zone the plugin's environment reports; where it reports none but UTC
 * the time is marked UTC rather than passed off as local, the weekly window's reset on the band among them. Countdowns
 * need no zone, so the band gives the 5-hour window's reset as one. A bill's day is a calendar day, which no zone shifts. A month is named from a table of its own, as the window names it
 * (windowtally/timeutil.py, MONTHS): the runtime's short names differ between versions (`Sept` or `Sep`).
 */

/** The plans status.json names, as a bill or a profile spells them. */
export const PLAN_NAMES: Readonly<Record<string, string>> = { pro: 'Pro', max5x: 'Max 5x', ultra: 'Ultra' }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const

/** `2 Nov` from a date's numeric `day` and `month` parts, as the window writes them: no leading zero, its month's name. */
function dayAndMonth(part: (type: string) => string): string {
  return `${Number(part('day'))} ${MONTHS[Number(part('month')) - 1] ?? part('month')}`
}

/** A day written YYYY-MM-DD, as `Sun 1 Nov`; the text itself when it is not one. */
export function day(text: string): string {
  const t = Date.parse(`${text}T00:00:00Z`)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || !Number.isFinite(t)) return text
  const parts = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short', day: 'numeric', month: 'numeric', timeZone: 'UTC',
  }).formatToParts(new Date(t))
  const part = (type: string) => parts.find(p => p.type === type)?.value ?? ''
  return `${part('weekday')} ${dayAndMonth(part)}`
}

/** Epoch ms of an ISO 8601 time, or null. */
export function parseTime(text: string | null | undefined): number | null {
  if (!text) return null
  const t = Date.parse(text)
  return Number.isFinite(t) ? t : null
}

export function percentText(value: number): string {
  return `${Math.round(value)}%`
}

/** A span of time, coarsest two units: `<1m`, `49m`, `1h 05m`, `4d 1h`. */
export function span(ms: number): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000)
  if (minutes < 1) return '<1m'
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

/** How long ago: `just now` under a minute, else `49m ago`. */
export function ago(ms: number): string {
  return ms < 60_000 ? 'just now' : `${span(ms)} ago`
}

function zoneIsUnknown(): boolean {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
    return !zone || zone === 'UTC' || zone === 'Etc/UTC'
  } catch {
    return true
  }
}

/** `Mon 01:07`, or with `withDate` `Mon 26 Oct 01:07`. */
export function when(epochMs: number, withDate = false): string {
  try {
    const parts = new Intl.DateTimeFormat('en-GB', {
      weekday: 'short', day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(new Date(epochMs))
    const part = (type: string) => parts.find(p => p.type === type)?.value ?? ''
    const time = `${part('hour')}:${part('minute')}`
    const text = withDate
      ? `${part('weekday')} ${dayAndMonth(part)} ${time}`
      : `${part('weekday')} ${time}`
    return zoneIsUnknown() ? `${text} UTC` : text
  } catch {
    return new Date(epochMs).toISOString().slice(0, 16).replace('T', ' ') + ' UTC'
  }
}
