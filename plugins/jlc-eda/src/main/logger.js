/**
 * In-memory diagnostic ring buffer.
 *
 * Credentials must never reach this buffer. Keys are redacted before storage;
 * strings are scrubbed for session_id/password/authorization patterns.
 */

const MAX_ENTRIES = 400;
const SECRET_KEY = /(pass(word|wd)?|pwd|secret|token|session[_-]?id|^sid$|cookie|authorization)/i;
const SECRET_TEXT = [
  /(session_id=)[^;\s]+/gi,
  /(password=)[^&\s]+/gi,
  /(authorization:\s*bearer\s+)[^\s]+/gi,
  /(cookie:\s*)[^\r\n]+/gi,
];

function scrubText(value) {
  let text = String(value);
  for (const pattern of SECRET_TEXT) text = text.replace(pattern, '$1[redacted]');
  return text;
}

export function redact(value, key = '', depth = 0) {
  if (depth > 6) return '[depth-limit]';
  if (SECRET_KEY.test(key)) return '[redacted]';
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') return scrubText(value);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.slice(0, 100).map((item) => redact(item, key, depth + 1));
  if (typeof value === 'object') {
    if (value instanceof Error) {
      return { name: value.name, code: value.code || null, message: scrubText(value.message) };
    }
    const output = {};
    for (const [childKey, childValue] of Object.entries(value)) {
      output[childKey] = redact(childValue, childKey, depth + 1);
    }
    return output;
  }
  return String(value);
}

export function createLogger(options = {}) {
  const entries = [];
  const now = options.now || (() => new Date());
  const consoleObj = options.consoleObj || (typeof console !== 'undefined' ? console : null);
  const maxEntries = options.maxEntries || MAX_ENTRIES;

  function stamp() {
    const date = now();
    const pad = (value, width = 2) => String(value).padStart(width, '0');
    return (
      date.getFullYear() +
      '-' +
      pad(date.getMonth() + 1) +
      '-' +
      pad(date.getDate()) +
      ' ' +
      pad(date.getHours()) +
      ':' +
      pad(date.getMinutes()) +
      ':' +
      pad(date.getSeconds()) +
      '.' +
      pad(date.getMilliseconds(), 3)
    );
  }

  function write(level, event, fields) {
    const entry = {
      ts: stamp(),
      level: String(level || 'INFO').toUpperCase(),
      event: scrubText(event || ''),
      fields: fields ? redact(fields) : {},
    };
    entries.push(entry);
    if (entries.length > maxEntries) entries.shift();
    if (consoleObj && typeof consoleObj.log === 'function') {
      try {
        consoleObj.log('[lab-inventory-v3]', entry.ts, entry.level, entry.event, entry.fields);
      } catch (_) {
        /* logging must never break the extension */
      }
    }
    return entry;
  }

  return {
    debug: (event, fields) => write('DEBUG', event, fields),
    info: (event, fields) => write('INFO', event, fields),
    warn: (event, fields) => write('WARN', event, fields),
    error: (event, fields) => write('ERROR', event, fields),
    snapshot: () => entries.map((entry) => ({ ...entry, fields: redact(entry.fields) })),
    toText: () =>
      entries
        .map((entry) => '[' + entry.ts + '] [' + entry.level + '] ' + entry.event + ' ' + JSON.stringify(entry.fields))
        .join('\n'),
    clear: () => {
      entries.length = 0;
    },
    redact,
  };
}
