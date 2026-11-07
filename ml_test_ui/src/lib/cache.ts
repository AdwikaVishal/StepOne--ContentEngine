/** LocalStorage-based job history cache */

export interface JobRecord {
  id: string
  eventName: string
  timestamp: number
  fileCount: number
  result: any
}

const KEY = 'ce_job_history'
const MAX = 10

export function saveJob(record: JobRecord) {
  try {
    const existing = loadJobs()
    const updated = [record, ...existing.filter(j => j.id !== record.id)].slice(0, MAX)
    localStorage.setItem(KEY, JSON.stringify(updated))
  } catch {}
}

export function loadJobs(): JobRecord[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') } catch { return [] }
}

export function clearJobs() {
  try { localStorage.removeItem(KEY) } catch {}
}
