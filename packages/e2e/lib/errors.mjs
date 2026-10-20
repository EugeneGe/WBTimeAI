/**
 * Red-cause classification and the shared Node-side failure types.
 *
 * Why this module exists
 * ----------------------
 * The reverse leg of S-6 must fail for the *right* reason. A refused connection
 * (`ECONNREFUSED`) or an unresolvable host (`ENOTFOUND`) proves "the process I
 * killed is really gone". A timeout (`ETIMEDOUT`) proves nothing — the socket
 * may be black-holed — and an assertion mismatch proves the request actually
 * **succeeded** (the request came back, so the assertion about failure blew up).
 * Both of those are 伪反证 (false refutation) and must exit `31`, never `0`.
 *
 * Exit codes (§3.3, Node segment 30–34):
 *   0  red for an allowed reason
 *   30 case not green
 *   31 red, but the cause is not legal (ETIMEDOUT / assertion mismatch / unknown)
 *   32 `X-E2E-Nonce` absent or mismatched
 *   33 executed-count mismatch, or skip/only/todo used
 *   34 precondition unavailable
 *
 * This module performs no I/O of its own.
 */

const EXIT_OK = 0;
const EXIT_NOT_GREEN = 30;
const EXIT_BAD_RED_CAUSE = 31;
const EXIT_NONCE = 32;
const EXIT_COUNT = 33;
const EXIT_PRECONDITION = 34;

/** Exit codes owned by `packages/e2e/**` (§3.3). */
export const EXIT = Object.freeze({
  OK: EXIT_OK,
  NOT_GREEN: EXIT_NOT_GREEN,
  BAD_RED_CAUSE: EXIT_BAD_RED_CAUSE,
  NONCE: EXIT_NONCE,
  COUNT: EXIT_COUNT,
  PRECONDITION: EXIT_PRECONDITION,
});

/**
 * The only causes that may make the reverse leg green.
 * `ENOTFOUND` is allowed because `localhost` resolution can fail on a machine
 * whose resolver is unhappy; both mean "no listener answered".
 */
export const ALLOWED_RED_CAUSES = Object.freeze(['ECONNREFUSED', 'ENOTFOUND']);

/** A timeout means "we don't know" — never a proof of absence. */
export const TIMEOUT_CAUSE = 'ETIMEDOUT';

/** The request came back, so the "it must fail" assertion blew up: 伪反证. */
export const ASSERTION_MISMATCH = 'ASSERTION_MISMATCH';

/** No structured code and no known token: also illegal (unknown ≠ allowed). */
export const UNKNOWN_CAUSE = 'UNKNOWN_CAUSE';

/** Structured `code` values we know how to name. */
export const KNOWN_CAUSES = Object.freeze([
  'ECONNREFUSED',
  'ENOTFOUND',
  'EAI_AGAIN',
  'ETIMEDOUT',
  'ESOCKETTIMEDOUT',
  'ECONNRESET',
  'ECONNABORTED',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'EADDRNOTAVAIL',
  'EPIPE',
  'EAI_FAIL',
  'CERT_HAS_EXPIRED',
  'ERR_TLS_CERT_ALTNAME_INVALID',
  'UND_ERR_CONNECT_TIMEOUT',
  'UND_ERR_SOCKET',
]);

/**
 * Token search over message text. Only used after structured codes and the
 * assertion check, so an `AssertionError` that merely *mentions* ECONNREFUSED
 * (assertion messages often quote the expected code) cannot be misclassified.
 */
const CAUSE_TOKEN_RE =
  /\b(ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ESOCKETTIMEDOUT|ECONNRESET|ECONNABORTED|EHOSTUNREACH|ENETUNREACH|EADDRNOTAVAIL|EPIPE|EAI_FAIL|CERT_HAS_EXPIRED|ERR_TLS_CERT_ALTNAME_INVALID|UND_ERR_CONNECT_TIMEOUT|UND_ERR_SOCKET)\b/;

/** Maximum depth walked through `Error.cause` / `AggregateError.errors`. */
const MAX_CAUSE_DEPTH = 6;

/**
 * Base class for every failure that carries a V0.0.2 exit code.
 *
 * `error.exitCode` is what `run_selfproof.py` (and CI) read; the code is part of
 * the contract, so it is set here and never re-derived from message text.
 */
export class GateFailure extends Error {
  /**
   * @param {string} message Single-line human readable reason.
   * @param {{exitCode?: number, causeCode?: string|null, details?: Record<string, unknown>}} [options]
   */
  constructor(message, options = {}) {
    super(message);
    const { exitCode = EXIT_NOT_GREEN, causeCode = null, details = {} } = options;
    this.name = new.target.name;
    this.exitCode = Number.isInteger(exitCode) ? exitCode : EXIT_NOT_GREEN;
    this.causeCode = causeCode;
    this.details = details;
  }

  /** @returns {{name: string, message: string, exitCode: number, causeCode: string|null}} */
  toJSON() {
    return {
      name: this.name,
      message: this.message,
      exitCode: this.exitCode,
      causeCode: this.causeCode,
    };
  }
}

/** Cases did not come out green (exit 30). */
export class CaseNotGreenError extends GateFailure {
  constructor(message, options = {}) {
    super(message, { ...options, exitCode: EXIT_NOT_GREEN });
  }
}

/** Red, but the cause is not in the allowed set (exit 31). */
export class PseudoRefutationError extends GateFailure {
  constructor(message, options = {}) {
    super(message, { ...options, exitCode: EXIT_BAD_RED_CAUSE });
  }
}

/** `X-E2E-Nonce` absent or mismatched on some response (exit 32). */
export class NonceMismatchError extends GateFailure {
  constructor(message, options = {}) {
    super(message, { ...options, exitCode: EXIT_NONCE });
  }
}

/** Nonce config invalid, e.g. `E2E_RUN_NONCE` not set (exit 34). */
export class NonceConfigError extends GateFailure {
  constructor(message, options = {}) {
    super(message, { ...options, exitCode: EXIT_PRECONDITION });
  }
}

/** Executed-count mismatch, or skip/only/todo used (exit 33). */
export class CountMismatchError extends GateFailure {
  constructor(message, options = {}) {
    super(message, { ...options, exitCode: EXIT_COUNT });
  }
}

/** Environment / backend precondition missing (exit 34). */
export class PreconditionError extends GateFailure {
  constructor(message, options = {}) {
    super(message, { ...options, exitCode: EXIT_PRECONDITION });
  }
}

/**
 * Is this an assertion failure rather than a transport failure?
 *
 * Checked *before* any text token search: an assertion message usually quotes
 * the expected cause, and treating that as the cause would invent a legal red.
 *
 * @param {unknown} error
 * @returns {boolean}
 */
export function isAssertionFailure(error) {
  if (!(error instanceof Error)) {
    return false;
  }
  if (error.name === 'AssertionError' || error.code === 'ERR_ASSERTION') {
    return true;
  }
  if (Array.isArray(error.errors)) {
    return error.errors.some((inner) => isAssertionFailure(inner));
  }
  return false;
}

/**
 * Walk the error graph for a structured `code`.
 *
 * @param {unknown} error
 * @param {number} depth
 * @param {Set<unknown>} seen Cycle guard.
 * @returns {string|null}
 */
function structuredCause(error, depth, seen) {
  if (error === null || typeof error !== 'object' || depth > MAX_CAUSE_DEPTH) {
    return null;
  }
  if (seen.has(error)) {
    return null;
  }
  seen.add(error);

  const structured = typeof error.code === 'string'
    ? error.code
    : (typeof error.errno === 'string' ? error.errno : null);

  if (Array.isArray(error.errors)) {
    for (const inner of error.errors) {
      const found = structuredCause(inner, depth + 1, seen);
      if (found !== null) {
        return found;
      }
    }
  }
  if (error.cause !== undefined && error.cause !== null) {
    const found = structuredCause(error.cause, depth + 1, seen);
    if (found !== null) {
      return found;
    }
  }
  return structured;
}

/**
 * Render any thrown value as one printable line.
 *
 * @param {unknown} error
 * @returns {string}
 */
export function describeError(error) {
  if (error === null || error === undefined) {
    return 'no error';
  }
  const flat = (text) => String(text).replace(/\r\n|\r|\n/g, ' | ');
  if (error instanceof Error) {
    const code = typeof error.code === 'string' ? ` [${error.code}]` : '';
    const cause = error.cause instanceof Error
      ? ` <- ${error.cause.name}: ${flat(error.cause.message)}`
      : '';
    return flat(`${error.name}${code}: ${error.message}${cause}`);
  }
  return flat(String(error));
}

/**
 * Extract the transport cause of a failure.
 *
 * Precedence: assertion → structured `code` (walking `cause` / `AggregateError`)
 * → known token inside the message → `UNKNOWN_CAUSE`.
 *
 * @param {unknown} error
 * @returns {string}
 */
export function extractCauseCode(error) {
  if (isAssertionFailure(error)) {
    return ASSERTION_MISMATCH;
  }
  const structured = structuredCause(error, 0, new Set());
  if (structured !== null && structured !== '') {
    return structured;
  }
  const match = describeError(error).match(CAUSE_TOKEN_RE);
  if (match) {
    return match[1];
  }
  return UNKNOWN_CAUSE;
}

/**
 * @param {string} cause
 * @returns {boolean} True when the cause may legally turn the reverse leg green.
 */
export function isAllowedRedCause(cause) {
  return ALLOWED_RED_CAUSES.includes(cause);
}

/**
 * Classify one thrown value.
 *
 * @param {unknown} error
 * @returns {{cause: string, allowed: boolean, pseudo: boolean, timeout: boolean,
 *            assertionMismatch: boolean, exitCode: number, detail: string}}
 */
export function classifyRedCause(error) {
  const cause = extractCauseCode(error);
  const allowed = isAllowedRedCause(cause);
  return {
    cause,
    allowed,
    // 伪反证: everything that is not in the allowed set, including ETIMEDOUT,
    // an assertion mismatch, and any unknown cause.
    pseudo: !allowed,
    timeout: cause === TIMEOUT_CAUSE,
    assertionMismatch: cause === ASSERTION_MISMATCH,
    exitCode: allowed ? EXIT.OK : EXIT.BAD_RED_CAUSE,
    detail: describeError(error),
  };
}

/**
 * Throw `PseudoRefutationError` (31) unless the failure reason is legal.
 *
 * @param {unknown} error
 * @param {{context?: string}} [options]
 * @returns {{cause: string, allowed: boolean, pseudo: boolean, timeout: boolean,
 *            assertionMismatch: boolean, exitCode: number, detail: string}}
 */
export function assertLegitimateRedCause(error, options = {}) {
  const { context = 'reverse leg' } = options;
  const verdict = classifyRedCause(error);
  if (verdict.allowed) {
    return verdict;
  }
  const hint = verdict.timeout
    ? 'ETIMEDOUT 不能证明进程已退出（socket 可能只是被黑洞）'
    : (verdict.assertionMismatch
      ? '断言不符 ⇒ 请求其实成功了 ⇒ 伪反证'
      : `未知/非法红因 ${verdict.cause}`);
  throw new PseudoRefutationError(
    `${context}: ${hint} (allowed=${ALLOWED_RED_CAUSES.join('/')}) :: ${verdict.detail}`,
    { causeCode: verdict.cause, details: verdict },
  );
}

/**
 * Assert a forward case came out green.
 *
 * @param {boolean} condition
 * @param {string} message
 * @param {{details?: Record<string, unknown>}} [options]
 * @returns {void}
 */
export function assertCaseGreen(condition, message, options = {}) {
  if (condition) {
    return;
  }
  throw new CaseNotGreenError(message, { details: options.details ?? {} });
}

/**
 * Assert an environment / backend precondition.
 *
 * @param {boolean} condition
 * @param {string} message
 * @returns {void}
 */
export function assertPrecondition(condition, message) {
  if (condition) {
    return;
  }
  throw new PreconditionError(message);
}

/**
 * Map a thrown value onto an exit code (no side effects).
 *
 * @param {unknown} error
 * @returns {number}
 */
export function exitCodeFor(error) {
  if (error instanceof GateFailure) {
    return error.exitCode;
  }
  return EXIT_NOT_GREEN;
}

/**
 * Write a failure to `stream` and return its exit code (does not call `process.exit`).
 *
 * @param {unknown} error
 * @param {{stream?: NodeJS.WritableStream}} [options]
 * @returns {number}
 */
export function reportFailure(error, options = {}) {
  const stream = options.stream ?? process.stderr;
  const code = exitCodeFor(error);
  const prefix = error instanceof GateFailure ? error.name : 'Error';
  stream.write(`[e2e] FAIL (exit ${code}) ${prefix}: ${describeError(error)}\n`);
  if (error instanceof GateFailure && Object.keys(error.details ?? {}).length > 0) {
    stream.write(`[e2e] FAIL details: ${JSON.stringify(error.details)}\n`);
  }
  return code;
}
