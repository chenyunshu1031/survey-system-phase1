const timeZone = 'Asia/Shanghai'

function dateParts(value: string): Record<string, string> {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) throw new Error('截止时间格式不正确')
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  })
  return Object.fromEntries(formatter.formatToParts(date).map(({ type, value: part }) => [type, part]))
}

export function formatBeijingInput(value: string | null): string {
  if (!value) return ''
  const parts = dateParts(value)
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

export function formatBeijingDisplay(value: string): string {
  const parts = dateParts(value)
  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}

export function parseBeijingInput(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) {
    throw new Error('请填写完整的截止日期和时间')
  }
  const date = new Date(`${value}+08:00`)
  if (Number.isNaN(date.getTime()) || formatBeijingInput(date.toISOString()) !== value) {
    throw new Error('截止时间格式不正确，请检查日期和时间是否存在')
  }
  return date.toISOString()
}
