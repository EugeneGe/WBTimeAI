/**
 * S-5 counting: `EXPECTED_CASES`, the skip/only/todo ban, and executed-count proof.
 *
 * Why (K-11 / K-12)
 * -----------------
 * A test suite that reports "0 failures" while running 1 of 4 cases, or while one
 * case is `skip`ped, is green for the wrong reason. So this module makes three
 * facts machine-checkable:
 *
 * 1. `EXPECTED_CASES = 4` — the DoD#4 case count, hard-coded (§1.2.2: 登录 / 401 单飞 /
 *    SSE 9 通道 / 分页).
 * 2. `skip` / `only` / `todo` must not appear in runner sources at all; if they do,
 *    the run is INVALID (exit 33), not "green with skips".
 * 3. The executed count must equal the expected count — checked both from inside
 *    the process (`CaseCounter`) and from the runner's own summary
 *    (`parseTapSummary` + `assertSummary`), so `run_selfproof.py` can verify it
 *    without trusting the tests.
 *
 * An unparseable/empty summary is a failure, never a pass (K-11: 空集合 ⇒ INVALID).
 *
 * Exit code: 33. This module performs no I/O of its own.
 */

import { CountMismatchError } from './errors.mjs';

/** The four DoD#4 cases (登录 / 401 单飞 / SSE 9 通道 / 分页). */
export const EXPECTED_CASES = 4;

/** Modifiers that must never appear in the runner (§7 K-12). */
export const FORBIDDEN_MODIFIERS = Object.freeze(['skip', 'only', 'todo']);

/**
 * Patterns per modifier, applied to comment-stripped source.
 *
 * Both the call form (`.skip(`) and the option form (`{ skip: true }`) are
 * banned: `test('x', { skip: true }, fn)` is the same lie as `test.skip`.
 */
export const MODIFIER_PATTERNS = Object.freeze({
  skip: Object.freeze([
    /\.skip\s*\(/,
    /\.skipIf\s*\(/,
    /\bskip\s*:\s*(?:true|['"`][^'"`]*['"`])/,
    /\bt\.skip\b/,
  ]),
  only: Object.freeze([
    /\.only\s*\(/,
    /\bonly\s*:\s*true\b/,
    /\bt\.only\b/,
  ]),
  todo: Object.freeze([
    /\.todo\s*\(/,
    /\btodo\s*:\s*(?:true|['"`][^'"`]*['"`])/,
    /\bt\.todo\b/,
  ]),
});

/** Summary keys parsed out of a Node test report. */
const SUMMARY_KEYS = Object.freeze(['tests', 'pass', 'fail', 'skipped', 'todo', 'cancelled']);

/**
 * Remove comments (and plain string bodies) from JavaScript source while
 * preserving line numbers.
 *
 * Line numbers must survive so a violation can be reported as `file:line`.
 * `'...'` / `"..."` bodies are blanked because a modifier *inside a string* is not
 * a call — a runner asserting on an error text that happens to contain `.only(`
 * must not be flagged. Template literals are copied verbatim instead, so a
 * `${...}` interpolation can never hide a real call. Template nesting and
 * regex-literal detection are deliberately not modelled: the scanner only ever
 * sees our own runner sources, and it fails **open** (it can under-strip a
 * comment, never invent code), which is the safe direction for a ban check.
 *
 * @param {string} source
 * @returns {string} Same length, newlines preserved, comments and string bodies blanked.
 */
export function stripComments(source) {
  const text = String(source ?? '');
  const out = [];
  let index = 0;
  let state = 'code';
  while (index < text.length) {
    const char = text[index];
    const next = text[index + 1];

    if (state === 'code') {
      if (char === '/' && next === '/') {
        state = 'line';
        out.push(' ', ' ');
        index += 2;
        continue;
      }
      if (char === '/' && next === '*') {
        state = 'block';
        out.push(' ', ' ');
        index += 2;
        continue;
      }
      if (char === "'" || char === '"' || char === '`') {
        state = char;
        out.push(char);
        index += 1;
        continue;
      }
      out.push(char);
      index += 1;
      continue;
    }

    if (state === 'line') {
      if (char === '\n') {
        state = 'code';
        out.push('\n');
      } else {
        out.push(' ');
      }
      index += 1;
      continue;
    }

    if (state === 'block') {
      if (char === '*' && next === '/') {
        state = 'code';
        out.push(' ', ' ');
        index += 2;
        continue;
      }
      out.push(char === '\n' ? '\n' : ' ');
      index += 1;
      continue;
    }

    // Inside a plain string: blank the body (keep escapes consumed, keep quotes).
    if (state === "'" || state === '"') {
      if (char === '\\') {
        out.push(' ', ' ');
        index += 2;
        continue;
      }
      if (char === state) {
        state = 'code';
        out.push(char);
        index += 1;
        continue;
      }
      out.push(char === '\n' ? '\n' : ' ');
      index += 1;
      continue;
    }

    // Inside a template literal: copy verbatim, honour backslash escapes.
    if (char === '\\') {
      out.push(char, next ?? '');
      index += 2;
      continue;
    }
    if (char === state) {
      state = 'code';
    }
    out.push(char);
    index += 1;
  }
  return out.join('');
}

/**
 * Find every forbidden modifier occurrence in a set of runner sources.
 *
 * @param {Array<{file: string, text: string}>} sources
 * @returns {Array<{file: string, line: number, modifier: string, excerpt: string}>}
 *   Violations sorted by file then line; empty when clean.
 */
export function findForbiddenModifiers(sources) {
  const violations = [];
  for (const source of sources ?? []) {
    const file = String(source?.file ?? '<unknown>');
    const stripped = stripComments(source?.text ?? '');
    const lines = stripped.split('\n');
    for (let position = 0; position < lines.length; position += 1) {
      const line = lines[position];
      for (const modifier of FORBIDDEN_MODIFIERS) {
        const patterns = MODIFIER_PATTERNS[modifier];
        if (patterns.some((pattern) => pattern.test(line))) {
          violations.push({
            file,
            line: position + 1,
            modifier,
            excerpt: line.trim().slice(0, 160),
          });
          break;
        }
      }
    }
  }
  violations.sort((left, right) => (
    left.file === right.file ? left.line - right.line : left.file.localeCompare(right.file)
  ));
  return violations;
}

/**
 * Throw when any forbidden modifier is present.
 *
 * @param {Array<{file: string, text: string}>} sources
 * @returns {void}
 * @throws {CountMismatchError} When `skip` / `only` / `todo` appears (exit 33).
 */
export function assertNoForbiddenModifiers(sources) {
  const violations = findForbiddenModifiers(sources);
  if (violations.length === 0) {
    return;
  }
  const rendered = violations
    .map((item) => `${item.file}:${item.line} ${item.modifier} :: ${item.excerpt}`)
    .join(' ; ');
  throw new CountMismatchError(
    `runner 源码出现 ${violations.length} 处 skip/only/todo（K-12 明令禁止）: ${rendered}`,
    { causeCode: 'FORBIDDEN_MODIFIER', details: { violations } },
  );
}

/**
 * Tracks declared vs executed cases from inside the test process.
 *
 * Usage (T05 test files): `register('case-1-login')` at load, `markExecuted(...)`
 * as the first statement of the test body, then `assertComplete()` in a final
 * `after()` hook.
 */
export class CaseCounter {
  #expected;
  #declared = [];
  #executed = [];
  #failures = [];

  /**
   * @param {number} [expected] Expected case count, defaults to `EXPECTED_CASES`.
   */
  constructor(expected = EXPECTED_CASES) {
    if (!Number.isInteger(expected) || expected <= 0) {
      throw new CountMismatchError(
        `CaseCounter 需要正整数期望值，收到 ${String(expected)}`,
        { causeCode: 'BAD_EXPECTED' },
      );
    }
    this.#expected = expected;
  }

  /** @returns {number} The expected case count. */
  get expected() {
    return this.#expected;
  }

  /** @returns {string[]} Declared case ids, in declaration order. */
  get declared() {
    return [...this.#declared];
  }

  /** @returns {string[]} Executed case ids, in execution order. */
  get executed() {
    return [...this.#executed];
  }

  /** @returns {number} How many cases actually ran. */
  get count() {
    return this.#executed.length;
  }

  /** @returns {Array<{caseId: string, reason: string}>} Per-case failures. */
  get failures() {
    return this.#failures.map((failure) => ({ ...failure }));
  }

  /** @returns {string[]} Declared-but-never-executed case ids. */
  missing() {
    return this.#declared.filter((caseId) => !this.#executed.includes(caseId));
  }

  /**
   * Declare a case id.
   *
   * @param {string} caseId Stable id, e.g. `"case-1-login"`.
   * @returns {void}
   * @throws {CountMismatchError} On a blank or duplicated id.
   */
  register(caseId) {
    const id = typeof caseId === 'string' ? caseId.trim() : '';
    if (id === '') {
      throw new CountMismatchError('CaseCounter.register 需要非空 caseId', {
        causeCode: 'BLANK_CASE_ID',
      });
    }
    if (this.#declared.includes(id)) {
      throw new CountMismatchError(`caseId 重复登记: ${id}`, {
        causeCode: 'DUPLICATE_CASE_ID',
        details: { caseId: id },
      });
    }
    this.#declared.push(id);
  }

  /**
   * Record that a case actually executed.
   *
   * @param {string} caseId
   * @returns {void}
   * @throws {CountMismatchError} When the id was never registered or runs twice.
   */
  markExecuted(caseId) {
    const id = typeof caseId === 'string' ? caseId.trim() : '';
    if (!this.#declared.includes(id)) {
      throw new CountMismatchError(`执行了未登记的 caseId: ${id || '<blank>'}`, {
        causeCode: 'UNREGISTERED_CASE',
        details: { caseId: id },
      });
    }
    if (this.#executed.includes(id)) {
      throw new CountMismatchError(`caseId 被执行两次: ${id}`, {
        causeCode: 'DUPLICATE_EXECUTION',
        details: { caseId: id },
      });
    }
    this.#executed.push(id);
  }

  /**
   * Record a failure for a case (kept for the evidence line).
   *
   * @param {string} caseId
   * @param {string} reason
   * @returns {void}
   */
  markFailed(caseId, reason) {
    this.#failures.push({ caseId: String(caseId), reason: String(reason) });
  }

  /**
   * Assert the run was complete: expected count, all declared cases executed, no
   * failures.
   *
   * @returns {void}
   * @throws {CountMismatchError} When anything above does not hold (exit 33).
   */
  assertComplete() {
    const problems = [];
    if (this.#declared.length !== this.#expected) {
      problems.push(`登记 ${this.#declared.length} 条，期望 ${this.#expected} 条`);
    }
    if (this.#executed.length !== this.#expected) {
      problems.push(`实际执行 ${this.#executed.length} 条，期望 ${this.#expected} 条`);
    }
    const missing = this.missing();
    if (missing.length > 0) {
      problems.push(`未执行: ${missing.join(',')}`);
    }
    if (this.#failures.length > 0) {
      problems.push(`失败 ${this.#failures.length} 条: ${this.#failures
        .map((failure) => `${failure.caseId}(${failure.reason})`).join(',')}`);
    }
    if (problems.length === 0) {
      return;
    }
    throw new CountMismatchError(
      `S-5 计数不符: ${problems.join(' ; ')}`,
      {
        causeCode: 'EXECUTION_COUNT',
        details: {
          expected: this.#expected,
          declared: this.declared,
          executed: this.executed,
          failures: this.failures,
        },
      },
    );
  }

  /**
   * One-line summary for evidence.
   *
   * @returns {string} e.g. `cases: executed=4/4 declared=4 failures=0`.
   */
  summary() {
    return `cases: executed=${this.#executed.length}/${this.#expected}`
      + ` declared=${this.#declared.length} failures=${this.#failures.length}`;
  }
}

/**
 * Parse the counts out of a Node test-runner report (TAP or spec reporter).
 *
 * @param {string} text Full stdout/stderr of `node --test`.
 * @returns {{tests: number|null, pass: number|null, fail: number|null,
 *            skipped: number|null, todo: number|null, cancelled: number|null,
 *            parsed: boolean}}
 *   `parsed` is `false` when no summary line was found — callers must treat that
 *   as INVALID, never as zero-failure success.
 */
export function parseTapSummary(text) {
  const body = String(text ?? '');
  const summary = { tests: null, pass: null, fail: null, skipped: null, todo: null, cancelled: null, parsed: false };
  for (const key of SUMMARY_KEYS) {
    const pattern = new RegExp(`^[\\s#ℹ]*${key}\\s+(\\d+)\\s*$`, 'm');
    const match = body.match(pattern);
    if (match) {
      summary[key] = Number.parseInt(match[1], 10);
      summary.parsed = true;
    }
  }
  return summary;
}

/**
 * Assert a parsed summary proves "4 of 4 ran, none skipped, none failed".
 *
 * @param {ReturnType<typeof parseTapSummary>} summary
 * @param {{expected?: number}} [options]
 * @returns {void}
 * @throws {CountMismatchError} When the summary is missing or inconsistent (exit 33).
 */
export function assertSummary(summary, options = {}) {
  const { expected = EXPECTED_CASES } = options;
  if (summary === null || summary === undefined || !summary.parsed) {
    throw new CountMismatchError(
      '无法从 runner 输出解析出汇总（空汇总 / 零输出 = 假绿，K-11）',
      { causeCode: 'UNPARSEABLE_SUMMARY' },
    );
  }
  const problems = [];
  if (summary.tests !== expected) {
    problems.push(`tests=${summary.tests} 期望 ${expected}`);
  }
  if (summary.pass !== expected) {
    problems.push(`pass=${summary.pass} 期望 ${expected}`);
  }
  if (summary.fail !== 0) {
    problems.push(`fail=${summary.fail} 期望 0`);
  }
  if (summary.skipped !== 0) {
    problems.push(`skipped=${summary.skipped} 期望 0（K-12 禁止 skip）`);
  }
  if (summary.todo !== 0) {
    problems.push(`todo=${summary.todo} 期望 0（K-12 禁止 todo）`);
  }
  if (summary.cancelled !== 0) {
    problems.push(`cancelled=${summary.cancelled} 期望 0`);
  }
  if (problems.length === 0) {
    return;
  }
  throw new CountMismatchError(
    `S-5 汇总不符: ${problems.join(' ; ')}`,
    { causeCode: 'SUMMARY_MISMATCH', details: { summary, expected } },
  );
}

/**
 * Assert an externally counted execution total.
 *
 * @param {number} executed
 * @param {{expected?: number}} [options]
 * @returns {void}
 * @throws {CountMismatchError} When the count is anything but exactly `expected`.
 */
export function assertExecutedExactly(executed, options = {}) {
  const { expected = EXPECTED_CASES } = options;
  if (Number.isInteger(executed) && executed === expected) {
    return;
  }
  throw new CountMismatchError(
    `实际执行 ${String(executed)} 条，期望恰好 ${expected} 条`,
    { causeCode: 'EXECUTION_COUNT', details: { executed, expected } },
  );
}

/**
 * One-line evidence rendering of a summary.
 *
 * @param {ReturnType<typeof parseTapSummary>} summary
 * @returns {string}
 */
export function formatSummary(summary) {
  if (summary === null || summary === undefined || !summary.parsed) {
    return 'cases: UNPARSEABLE';
  }
  return `cases: tests=${summary.tests} pass=${summary.pass} fail=${summary.fail}`
    + ` skipped=${summary.skipped} todo=${summary.todo} cancelled=${summary.cancelled}`;
}
