const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'
const HAS_TZ_SUFFIX_RE = /(Z|[+-]\d{2}:?\d{2})$/i
const ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

function normalizeDateInput(value) {
  if (typeof value !== 'string') return value
  const raw = value.trim()
  if (!raw) return raw
  if (ISO_DATETIME_RE.test(raw) && !HAS_TZ_SUFFIX_RE.test(raw)) {
    return `${raw.replace(' ', 'T')}Z`
  }
  return raw
}

export function formatShanghaiDateTime(value, { includeSeconds = true } = {}) {
  if (!value) return ''
  const d = value instanceof Date ? value : new Date(normalizeDateInput(value))
  if (Number.isNaN(d.getTime())) return typeof value === 'string' ? value : ''

  const options = {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }
  if (includeSeconds) {
    options.second = '2-digit'
  }

  return new Intl.DateTimeFormat('zh-CN', options).format(d)
}
