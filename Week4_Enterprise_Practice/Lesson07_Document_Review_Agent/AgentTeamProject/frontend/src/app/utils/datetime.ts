export function parseApiDate(value: string): Date {
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

export function formatApiDate(value: string, options?: Intl.DateTimeFormatOptions): string {
  return parseApiDate(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    ...options,
  });
}

export function isSameLocalDay(value: string, date = new Date()): boolean {
  const parsed = parseApiDate(value);
  return parsed.getFullYear() === date.getFullYear()
    && parsed.getMonth() === date.getMonth()
    && parsed.getDate() === date.getDate();
}

export function isSameLocalMonth(value: string, date = new Date()): boolean {
  const parsed = parseApiDate(value);
  return parsed.getFullYear() === date.getFullYear()
    && parsed.getMonth() === date.getMonth();
}
