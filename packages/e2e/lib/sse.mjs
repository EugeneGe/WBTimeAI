/**
 * SSE frame parsing plus the 9-channel acceptance matrix (channel → scenario).
 *
 * Contract inputs (`contracts/sse/channels.json`, frozen, read-only):
 *   * `frame_format.data_frame.line_layout` = `id: <int> / event: <channel> / data: <json>`,
 *     frames terminated by a blank line (逐字节可比，不得追加换行);
 *   * `frame_format.heartbeat.sample` = `": hb <ms>\\n\\n"` — a comment frame, no `id:`,
 *     must not pollute `Last-Event-ID`;
 *   * `by_channel` maps channel → domain type (e.g. `tool.started` → `tool_call.started`),
 *     so a live stream may carry either name on the wire.
 *
 * Acceptance (§1.2.2, fixed): 3 scenarios, union of channels ⊇ the 9 core channels,
 * each observed at least once:
 *
 * | scenario  | channels |
 * |-----------|----------|
 * | `s-main`  | agent.started, agent.thinking, message.delta, tool.started, tool.completed, agent.completed |
 * | `s-mcp`   | mcp.started, mcp.completed |
 * | `s-error` | agent.error |
 *
 * 诚实边界: the matrix is a *fixture-level* expectation table. Passing it must never
 * be reported as "9 条实帧已验证" — the ledger records `9/9` only when every channel
 * was observed on a real stream, otherwise `8/9` + 未验证（依赖不可得）.
 *
 * Exit code: 30 (coverage not met → cases not green). No I/O of its own.
 */

import { CaseNotGreenError } from './errors.mjs';

/** The 9 core channels (DoD#4 用例 3). */
export const CORE_CHANNELS = Object.freeze([
  'agent.started',
  'agent.thinking',
  'message.delta',
  'tool.started',
  'tool.completed',
  'agent.completed',
  'mcp.started',
  'mcp.completed',
  'agent.error',
]);

/** Channel sets expected per run scenario (§1.2.2). */
export const SCENARIO_CHANNELS = Object.freeze({
  's-main': Object.freeze([
    'agent.started',
    'agent.thinking',
    'message.delta',
    'tool.started',
    'tool.completed',
    'agent.completed',
  ]),
  's-mcp': Object.freeze(['mcp.started', 'mcp.completed']),
  's-error': Object.freeze(['agent.error']),
});

/** Scenario ids, in run order. */
export const SCENARIOS = Object.freeze(Object.keys(SCENARIO_CHANNELS));

/**
 * Reverse index: channel → scenario. Built at load time and validated, because a
 * drifted constant table would silently weaken the 9-channel acceptance.
 *
 * @returns {Readonly<Record<string, string>>}
 */
function buildChannelScenario() {
  const map = {};
  for (const scenario of SCENARIOS) {
    for (const channel of SCENARIO_CHANNELS[scenario]) {
      if (Object.prototype.hasOwnProperty.call(map, channel)) {
        throw new Error(`SSE 矩阵自相矛盾: ${channel} 同时属于 ${map[channel]} 与 ${scenario}`);
      }
      map[channel] = scenario;
    }
  }
  const covered = Object.keys(map);
  const missing = CORE_CHANNELS.filter((channel) => !covered.includes(channel));
  const extra = covered.filter((channel) => !CORE_CHANNELS.includes(channel));
  if (missing.length > 0 || extra.length > 0) {
    throw new Error(
      `SSE 矩阵与 9 通道不一致: missing=${missing.join(',') || '-'} extra=${extra.join(',') || '-'}`,
    );
  }
  return Object.freeze(map);
}

/** channel → scenario, derived and validated against `CORE_CHANNELS`. */
export const CHANNEL_SCENARIO = buildChannelScenario();

/** Frame separator: a blank line (CRLF / LF / CR tolerant). */
const FRAME_SEPARATOR_RE = /\r\n\r\n|\r\r|\n\n/;

/** Line separator inside one frame. */
const LINE_SEPARATOR_RE = /\r\n|\r|\n/;

/** Raised when a frame block cannot be interpreted at all. */
export class SseParseError extends Error {
  /**
   * @param {string} message
   * @param {{raw?: string}} [options]
   */
  constructor(message, options = {}) {
    super(message);
    this.name = 'SseParseError';
    this.raw = options.raw ?? '';
  }
}

/**
 * Build a domain-type → channel index from `byChannel` (channel → domain type).
 *
 * @param {Record<string, string>|null|undefined} byChannel
 * @returns {Map<string, string>}
 */
export function buildDomainIndex(byChannel) {
  const index = new Map();
  for (const [channel, domain] of Object.entries(byChannel ?? {})) {
    if (typeof domain === 'string' && domain.trim() !== '') {
      index.set(domain, channel);
    }
  }
  return index;
}

/**
 * Normalise a wire name onto a channel name.
 *
 * A live stream may emit either the channel (`tool.started`) or the domain type
 * (`tool_call.started`); `byChannel` disambiguates. Unknown names are returned
 * unchanged so the caller can still report them.
 *
 * @param {string|null|undefined} name
 * @param {Map<string, string>|null} [domainIndex]
 * @returns {string|null}
 */
export function normalizeChannel(name, domainIndex = null) {
  if (typeof name !== 'string') {
    return null;
  }
  const trimmed = name.trim();
  if (trimmed === '') {
    return null;
  }
  if (domainIndex instanceof Map && domainIndex.has(trimmed)) {
    return domainIndex.get(trimmed);
  }
  return trimmed;
}

/**
 * Parse one frame block (no trailing blank line) into a frame record.
 *
 * @param {string} raw
 * @param {Map<string, string>|null} [domainIndex]
 * @returns {{type: 'event'|'comment', id: string|null, event: string|null,
 *            channel: string|null, data: unknown, dataText: string,
 *            retry: number|null, comment: string|null, raw: string}|null}
 *   `null` when the block carries nothing (pure whitespace).
 */
export function parseFrameBlock(raw, domainIndex = null) {
  const block = String(raw ?? '');
  if (block.trim() === '') {
    return null;
  }

  const lines = block.split(LINE_SEPARATOR_RE);
  const dataLines = [];
  let id = null;
  let event = null;
  let retry = null;
  const comments = [];

  for (const line of lines) {
    if (line === '') {
      continue;
    }
    if (line.startsWith(':')) {
      comments.push(line.slice(1).trim());
      continue;
    }
    const separator = line.indexOf(':');
    if (separator === -1) {
      // Field with no colon: the whole line is the field name with an empty value.
      continue;
    }
    const field = line.slice(0, separator);
    const value = line.slice(separator + 1).replace(/^ /, '');
    if (field === 'id') {
      id = value;
    } else if (field === 'event') {
      event = value;
    } else if (field === 'data') {
      dataLines.push(value);
    } else if (field === 'retry') {
      const parsed = Number.parseInt(value, 10);
      retry = Number.isNaN(parsed) ? null : parsed;
    }
  }

  const dataText = dataLines.join('\n');
  if (dataText === '' && event === null && id === null) {
    // A pure comment block (heartbeat).
    return {
      type: 'comment',
      id: null,
      event: null,
      channel: null,
      data: null,
      dataText: '',
      retry,
      comment: comments.join(' | ') || null,
      raw: block,
    };
  }

  let data = null;
  if (dataText !== '') {
    try {
      data = JSON.parse(dataText);
    } catch {
      data = null;
    }
  }

  const channel = normalizeChannel(event, domainIndex);

  return {
    type: 'event',
    id,
    event,
    channel,
    data,
    dataText,
    retry,
    comment: comments.join(' | ') || null,
    raw: block,
  };
}

/**
 * Incremental SSE parser — `push()` chunk by chunk, `end()` at stream end.
 *
 * Chunk boundaries are arbitrary (a frame may be split mid-JSON), so buffering is
 * mandatory: parsing per chunk would invent frames that never existed.
 */
export class SseStreamParser {
  #buffer = '';
  #frames = [];
  #domainIndex;

  /**
   * @param {{byChannel?: Record<string, string>|null}} [options]
   */
  constructor(options = {}) {
    const { byChannel = null } = options;
    this.#domainIndex = byChannel ? buildDomainIndex(byChannel) : null;
  }

  /**
   * Feed a chunk.
   *
   * @param {string|Uint8Array} chunk
   * @returns {Array<ReturnType<typeof parseFrameBlock>>} Frames completed by this chunk.
   */
  push(chunk) {
    this.#buffer += typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8');
    const completed = [];
    for (;;) {
      const match = FRAME_SEPARATOR_RE.exec(this.#buffer);
      if (match === null) {
        break;
      }
      const raw = this.#buffer.slice(0, match.index);
      this.#buffer = this.#buffer.slice(match.index + match[0].length);
      const frame = parseFrameBlock(raw, this.#domainIndex);
      if (frame !== null) {
        completed.push(frame);
      }
    }
    this.#frames.push(...completed);
    return completed;
  }

  /**
   * Flush the remaining buffer as a final frame (streams often omit the last blank line).
   *
   * @returns {Array<ReturnType<typeof parseFrameBlock>>}
   */
  end() {
    const rest = this.#buffer;
    this.#buffer = '';
    if (rest.trim() === '') {
      return [];
    }
    const frame = parseFrameBlock(rest, this.#domainIndex);
    if (frame === null) {
      return [];
    }
    this.#frames.push(frame);
    return [frame];
  }

  /** @returns {Array<ReturnType<typeof parseFrameBlock>>} Every frame seen so far. */
  get frames() {
    return [...this.#frames];
  }
}

/**
 * Convenience: parse a full SSE body in one call.
 *
 * @param {string} text
 * @param {{byChannel?: Record<string, string>|null}} [options]
 * @returns {Array<ReturnType<typeof parseFrameBlock>>}
 */
export function parseSse(text, options = {}) {
  const parser = new SseStreamParser(options);
  const frames = [...parser.push(String(text ?? ''))];
  frames.push(...parser.end());
  return frames;
}

/**
 * Collect the channel names observed in a frame list (comment frames excluded).
 *
 * @param {Array<ReturnType<typeof parseFrameBlock>>} frames
 * @returns {Set<string>}
 */
export function collectChannels(frames) {
  const seen = new Set();
  for (const frame of frames ?? []) {
    if (frame !== null && frame.type === 'event' && typeof frame.channel === 'string') {
      seen.add(frame.channel);
    }
  }
  return seen;
}

/**
 * Build the per-channel / per-scenario coverage matrix for evidence.
 *
 * @param {Iterable<string>} seenChannels
 * @returns {{total: number, observed: number, missing: string[],
 *            scenarios: Record<string, {expected: string[], observed: string[],
 *            missing: string[], complete: boolean}>}}
 */
export function coverageMatrix(seenChannels) {
  const seen = new Set(seenChannels ?? []);
  const observedList = CORE_CHANNELS.filter((channel) => seen.has(channel));
  const missing = CORE_CHANNELS.filter((channel) => !seen.has(channel));
  const scenarios = {};
  for (const scenario of SCENARIOS) {
    const expected = [...SCENARIO_CHANNELS[scenario]];
    const observed = expected.filter((channel) => seen.has(channel));
    scenarios[scenario] = {
      expected,
      observed,
      missing: expected.filter((channel) => !seen.has(channel)),
      complete: observed.length === expected.length,
    };
  }
  return {
    total: CORE_CHANNELS.length,
    observed: observedList.length,
    missing,
    scenarios,
  };
}

/**
 * One-line evidence rendering (K-7 log shape).
 *
 * @param {ReturnType<typeof coverageMatrix>} matrix
 * @returns {string} e.g. `sse coverage: 6/9 channels observed; missing=mcp.started,...`
 */
export function formatCoverageLine(matrix) {
  const missing = matrix.missing.length > 0 ? matrix.missing.join(',') : '-';
  const perScenario = SCENARIOS
    .map((scenario) => {
      const entry = matrix.scenarios[scenario];
      return `${scenario}=${entry.observed.length}/${entry.expected.length}`;
    })
    .join(' ');
  return `sse coverage: ${matrix.observed}/${matrix.total} channels observed`
    + ` missing=${missing} ${perScenario}`;
}

/**
 * Assert coverage of the whole 9-channel set.
 *
 * @param {Iterable<string>} seenChannels
 * @param {{expected?: readonly string[]}} [options]
 * @returns {ReturnType<typeof coverageMatrix>} The matrix when complete.
 * @throws {CaseNotGreenError} When any expected channel was never observed (exit 30).
 */
export function assertChannelCoverage(seenChannels, options = {}) {
  const { expected = CORE_CHANNELS } = options;
  const seen = new Set(seenChannels ?? []);
  const missing = expected.filter((channel) => !seen.has(channel));
  const matrix = coverageMatrix(seen);
  if (missing.length === 0) {
    return matrix;
  }
  throw new CaseNotGreenError(
    `${formatCoverageLine(matrix)} ⇒ 缺 ${missing.length} 条通道（不得用映射表断言冒充实帧）`,
    { causeCode: 'SSE_COVERAGE', details: { missing, matrix } },
  );
}

/**
 * Assert one scenario produced all of its channels.
 *
 * @param {string} scenario One of `SCENARIOS`.
 * @param {Iterable<string>} seenChannels
 * @returns {void}
 * @throws {CaseNotGreenError} On an unknown scenario or a missing channel (exit 30).
 */
export function assertScenarioCoverage(scenario, seenChannels) {
  const expected = SCENARIO_CHANNELS[scenario];
  if (expected === undefined) {
    throw new CaseNotGreenError(
      `未知 SSE 场景 ${String(scenario)}（允许: ${SCENARIOS.join('/')}）`,
      { causeCode: 'UNKNOWN_SCENARIO', details: { scenario } },
    );
  }
  const seen = new Set(seenChannels ?? []);
  const missing = expected.filter((channel) => !seen.has(channel));
  if (missing.length === 0) {
    return;
  }
  throw new CaseNotGreenError(
    `场景 ${scenario} 缺通道: ${missing.join(',')}（期望 ${expected.length} 条）`,
    { causeCode: 'SSE_SCENARIO_COVERAGE', details: { scenario, missing } },
  );
}
