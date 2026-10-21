/**
 * Shared harness for the four DoD#4 cases and the reverse leg.
 *
 * Two run modes, chosen by the environment — never by a code edit:
 *
 * | mode | trigger | who owns the process |
 * |------|---------|----------------------|
 * | `orchestrated` | `E2E_BASE_URL` is set (by `run_selfproof.py`) | the orchestrator: spawn, attest, kill, read-only diff |
 * | `standalone`   | `E2E_BASE_URL` is not set | this harness: it spawns `legacy_backend_launcher.py` itself |
 *
 * Why standalone exists: `node --test "tests/e2e/**\/*.test.mjs"` must be a real
 * proof on its own, not a green that only means "the orchestrator was there".
 * Each standalone file boots its **own** backend on its **own** port, so the
 * proof stays per-file and no state is shared between test processes (node runs
 * test files in parallel child processes).
 *
 * The nonce is generated **here** (`crypto.randomUUID()`), passed to the child
 * only through `E2E_RUN_NONCE`, and compared on **every** response (S-2).
 * Ledger wording red line (D-1): the header proves *this response came from the
 * process this runner spawned*, never "the Python backend implements nonce".
 *
 * No third-party imports: `node:` builtins plus `../lib/*.mjs` only.
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readdir, readFile, rm } from 'node:fs/promises';
import { createServer, connect } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { CaseNotGreenError, PreconditionError } from '../lib/errors.mjs';
import { assertNoForbiddenModifiers } from '../lib/counts.mjs';
import { NonceGuard, generateNonce, resolveNonce } from '../lib/nonce.mjs';
import { SseStreamParser } from '../lib/sse.mjs';

/** `packages/e2e/tests` — the directory this file lives in. */
export const TESTS_DIR = dirname(fileURLToPath(import.meta.url));

/** `packages/e2e`. */
export const PACKAGE_DIR = resolve(TESTS_DIR, '..');

/** Repository root (`D:/WBT/WBTimeAI`). */
export const REPO_ROOT = resolve(PACKAGE_DIR, '..', '..');

/** The launcher (child mode spawns the real backend). */
export const LAUNCHER = join(REPO_ROOT, 'scripts', 'selfproof', 'legacy_backend_launcher.py');

/** Frozen contract carrying `by_channel` (read-only; direction is channel → domain type, §11.2). */
export const CHANNELS_CONTRACT = join(REPO_ROOT, 'contracts', 'sse', 'channels.json');

/** Which leg this process is running: `forward` (default) or `reverse`. */
export const LEG = (process.env.E2E_LEG ?? 'forward').trim() || 'forward';

/** Orchestrated base URL, empty in standalone mode. */
const ENV_BASE_URL = (process.env.E2E_BASE_URL ?? '').trim();

/** True when `run_selfproof.py` owns the backend. */
export const ORCHESTRATED = ENV_BASE_URL !== '';

/**
 * Resolve a bare command name against `PATH`, returning an absolute path or `null`.
 *
 * Needed because {@link LEGACY_PYTHON} is validated downstream with `existsSync`,
 * which treats a bare name as a *relative file* and therefore never finds a
 * command that lives on `PATH`. Returning `'python3'` as a fallback made the
 * harness report `legacy 解释器不存在: python3` on a host that clearly *has*
 * python3 — a false negative that hid the real cause (missing fastapi/uvicorn).
 *
 * @param {string} command Bare command name, e.g. `python3`.
 * @returns {string|null} Absolute path, or `null` when not on `PATH`.
 */
function resolveOnPath(command) {
  const pathEnv = process.env.PATH ?? '';
  const separator = process.platform === 'win32' ? ';' : ':';
  const suffixes = process.platform === 'win32' ? ['.exe', '.cmd', '.bat', ''] : [''];
  for (const dir of pathEnv.split(separator)) {
    if (!dir) continue;
    for (const suffix of suffixes) {
      const candidate = join(dir, command + suffix);
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

/**
 * Read-only legacy tree (G-1).
 *
 * Candidates, in order — mirroring `scripts/_gate_io.py::_default_legacy_root`:
 *   1. `$E2E_LEGACY_ROOT`
 *   2. `<repo>/_old`             — in-repo archive convention (V0.1.0+)
 *   3. `<repo>/../WBTimeAI_old`  — sibling archive (older layout)
 *   4. `<repo>/_old`             — the *expected* path, returned even when absent
 *
 * The last candidate is deliberately a repo-relative path, never a hard-coded
 * absolute one. Until 2026-10-21 this fell back to `'D:/WBT/WBTimeAI_old'`, which
 * on Linux produced `legacy 解释器不存在: D:/WBT/.../python.exe` — a message that
 * names a Windows path no Linux host can satisfy, so the real cause ("the archive
 * is elsewhere") was invisible. See `V0.1.0/03-台账/风险与决策.md` D-10.
 */
export const LEGACY_ROOT = (process.env.E2E_LEGACY_ROOT ?? '').trim()
  || [join(REPO_ROOT, '_old'), resolve(REPO_ROOT, '..', 'WBTimeAI_old')]
    .find((candidate) => existsSync(candidate))
  || join(REPO_ROOT, '_old');

/**
 * Interpreter that can import fastapi/uvicorn (the legacy venv; G-2).
 *
 * Resolution order:
 *   1. `$E2E_LEGACY_PYTHON` — explicit override.
 *   2. The legacy venv interpreter, **by platform**: `.venv/Scripts/python.exe`
 *      on Windows, `.venv/bin/python` / `python3` elsewhere.
 *   3. `python3` / `python` resolved **against `PATH`** into an absolute path.
 *   4. `<LEGACY_ROOT>/.venv/bin/python` — the expected location, absent on purpose.
 *
 * Steps 3 and 4 exist so the downstream `existsSync` check reports something
 * actionable: with a real interpreter the failure becomes "cannot import fastapi"
 * (the true blocker), and without one the message names the path the operator
 * should create instead of an impossible Windows path.
 */
export const LEGACY_PYTHON = (process.env.E2E_LEGACY_PYTHON ?? '').trim()
  || [
    join(LEGACY_ROOT, '.venv', 'Scripts', 'python.exe'),
    join(LEGACY_ROOT, '.venv', 'bin', 'python'),
    join(LEGACY_ROOT, '.venv', 'bin', 'python3'),
  ].find((candidate) => existsSync(candidate))
  || resolveOnPath('python3')
  || resolveOnPath('python')
  || join(LEGACY_ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

/** How long a boot may take (ms). */
const BOOT_TIMEOUT_MS = 90_000;

/** How long a request may take (ms). */
const REQUEST_TIMEOUT_MS = 120_000;

/** How long to wait for a killed port to stop answering (ms). */
const KILL_TIMEOUT_MS = 20_000;

/**
 * Whether a spawned child has finished (by exit code **or** by signal).
 *
 * `child.exitCode` stays `null` when the process was killed by a signal — on
 * Windows `child.kill()` always lands there — so testing only `exitCode` would
 * wait out the whole timeout and report a kill that actually worked as a failure.
 *
 * @param {import('node:child_process').ChildProcess} child
 * @returns {boolean}
 */
function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

/** Third-party msw must never appear in the runner either. */
const FORBIDDEN_IN_RUNNER = ['msw', 'vitest', 'undici', 'supertest'];

/**
 * Whether this process should register the tests of `leg`.
 *
 * @param {'forward'|'reverse'} leg
 * @returns {boolean}
 */
export function runsLeg(leg) {
  return LEG === leg;
}

/**
 * Assert the runner's own sources are free of `skip`/`only`/`todo` and of any
 * mock framework (K-12 + S-1 spirit).
 *
 * @returns {Promise<void>}
 * @throws {import('../lib/errors.mjs').CountMismatchError} When a modifier or a mock import is found.
 */
export async function assertRunnerSourcesClean() {
  const files = await collectTestSources(TESTS_DIR);
  assertNoForbiddenModifiers(files.map(({ file, text }) => ({ file, text })));
  const offenders = [];
  for (const { file, text } of files) {
    for (const name of FORBIDDEN_IN_RUNNER) {
      if (new RegExp(`from\\s*['"]${name}`, 'i').test(text) || new RegExp(`require\\(\\s*['"]${name}`, 'i').test(text)) {
        offenders.push(`${file} imports ${name}`);
      }
    }
  }
  if (offenders.length > 0) {
    throw new CaseNotGreenError(`runner 引入了 mock 框架: ${offenders.join(' ; ')}`, {
      causeCode: 'MOCK_FRAMEWORK',
      details: { offenders },
    });
  }
}

/**
 * Recursively collect `*.${test}.mjs` sources.
 *
 * @param {string} directory
 * @returns {Promise<Array<{file: string, text: string}>>}
 */
async function collectTestSources(directory) {
  const collected = [];
  const entries = await readdir(directory, { withFileTypes: true });
  for (const entry of entries) {
    const absolute = join(directory, entry.name);
    if (entry.isDirectory()) {
      collected.push(...await collectTestSources(absolute));
    } else if (entry.name.endsWith('.test.mjs')) {
      collected.push({ file: absolute.slice(REPO_ROOT.length + 1).replaceAll('\\', '/'), text: await readFile(absolute, 'utf8') });
    }
  }
  return collected;
}

/**
 * Find a free TCP port.
 *
 * @returns {Promise<number>}
 */
async function freePort() {
  return new Promise((resolvePort, rejectPort) => {
    const server = createServer();
    server.unref();
    server.on('error', rejectPort);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address !== null ? address.port : 0;
      server.close(() => (port > 0 ? resolvePort(port) : rejectPort(new Error('no free port'))));
    });
  });
}

/**
 * Whether something is listening on `port`.
 *
 * @param {number} port
 * @param {number} [timeoutMs]
 * @returns {Promise<boolean>}
 */
export async function isListening(port, timeoutMs = 1000) {
  return new Promise((resolveProbe) => {
    const socket = connect({ port, host: '127.0.0.1' });
    const done = (value) => {
      socket.removeAllListeners();
      socket.destroy();
      resolveProbe(value);
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

/**
 * Poll `/health` until it answers 200.
 *
 * @param {string} baseUrl
 * @param {{timeoutMs?: number, child?: import('node:child_process').ChildProcess}} [options]
 * @returns {Promise<void>}
 * @throws {PreconditionError} When the backend never becomes healthy (exit 34).
 */
async function waitForHealth(baseUrl, options = {}) {
  const { timeoutMs = BOOT_TIMEOUT_MS, child = undefined } = options;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child !== undefined && hasExited(child)) {
      throw new PreconditionError(
        `后端进程在启动期间退出（code=${child.exitCode}）；先跑 launcher --check 看 G-1..G-6`,
      );
    }
    try {
      const response = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(3000) });
      if (response.status === 200) {
        return;
      }
    } catch {
      // not up yet
    }
    await new Promise((resolveTick) => setTimeout(resolveTick, 250));
  }
  throw new PreconditionError(`后端 ${baseUrl}/health 在 ${timeoutMs}ms 内未就绪（G-2/G-5）`);
}

/**
 * A backend the tests can talk to.
 *
 * @typedef {object} BackendContext
 * @property {string} baseUrl
 * @property {string} nonce
 * @property {number} port
 * @property {boolean} orchestrated
 * @property {number|null} spawnedPid
 * @property {() => Promise<void>} stop
 */

/**
 * Start (standalone) or attach to (orchestrated) a backend and hand it to `body`.
 *
 * @template T
 * @param {string} label Short label used in the scratch directory name.
 * @param {(context: BackendContext) => Promise<T>} body
 * @returns {Promise<T>}
 */
export async function withBackend(label, body) {
  const context = await startBackend(label);
  try {
    return await body(context);
  } finally {
    await context.stop();
  }
}

/**
 * Start (standalone) or attach to (orchestrated) a backend.
 *
 * The returned context owns `stop()`; callers **must** call it (test files do so
 * from an `after()` hook), otherwise a standalone backend would outlive the process.
 *
 * @param {string} label Short label used in the scratch directory name.
 * @returns {Promise<BackendContext>}
 * @throws {PreconditionError} When the interpreter is missing or the boot fails (34).
 */
export async function startBackend(label) {
  if (ORCHESTRATED) {
    const nonce = resolveNonce();
    const url = new URL(ENV_BASE_URL);
    return {
      baseUrl: ENV_BASE_URL.replace(/\/$/, ''),
      nonce,
      port: Number.parseInt(url.port || '80', 10),
      orchestrated: true,
      spawnedPid: null,
      stop: async () => {},
    };
  }

  if (!existsSync(LEGACY_PYTHON)) {
    throw new PreconditionError(`legacy 解释器不存在: ${LEGACY_PYTHON}（G-2 ⇒ 段 II BLOCKED）`);
  }
  const port = Number.parseInt(process.env.E2E_PORT ?? '', 10) || await freePort();
  const nonce = generateNonce();
  const workdir = join(REPO_ROOT, 'output', 'e2e', `node-${label}-${process.pid}-${Date.now()}`);
  const child = spawn(
    LEGACY_PYTHON,
    [
      '-B',
      LAUNCHER,
      '--serve',
      '--port',
      String(port),
      '--workdir',
      workdir,
      '--legacy-root',
      LEGACY_ROOT,
    ],
    {
      cwd: REPO_ROOT,
      env: { ...process.env, E2E_RUN_NONCE: nonce, PYTHONDONTWRITEBYTECODE: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  const tail = [];
  const collect = (chunk) => {
    for (const line of String(chunk).split(/\r?\n/)) {
      if (line.trim() !== '') {
        tail.push(line.trim());
        if (tail.length > 40) {
          tail.shift();
        }
      }
    }
  };
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', collect);
  child.stderr.on('data', collect);

  const baseUrl = `http://127.0.0.1:${port}`;
  const stop = async () => {
    if (!hasExited(child)) {
      child.kill('SIGTERM');
      const deadline = Date.now() + KILL_TIMEOUT_MS;
      let closed = false;
      while (Date.now() < deadline) {
        if (hasExited(child) && !(await isListening(port))) {
          closed = true;
          break;
        }
        await new Promise((resolveTick) => setTimeout(resolveTick, 100));
      }
      if (!closed) {
        child.kill('SIGKILL');
        await new Promise((resolveTick) => setTimeout(resolveTick, 250));
      }
    }
    // The scratch directory holds a database copy per run: drop it unless kept.
    if ((process.env.E2E_KEEP ?? '') === '') {
      await rm(workdir, { recursive: true, force: true });
    }
  };

  try {
    await waitForHealth(baseUrl, { child });
  } catch (error) {
    await stop();
    const detail = tail.slice(-8).join(' | ');
    throw new PreconditionError(`${String(error.message)} :: child-tail=${detail}`);
  }

  return {
    baseUrl, nonce, port, orchestrated: false, spawnedPid: child.pid, stop,
  };
}

/**
 * Perform one JSON request and record its `X-E2E-Nonce` verdict (S-2: every
 * response, not just the first).
 *
 * @param {NonceGuard} guard
 * @param {object} request
 * @param {string} request.baseUrl
 * @param {string} [request.method]
 * @param {string} request.path
 * @param {unknown} [request.body]
 * @param {string|null} [request.token]
 * @param {Record<string,string>} [request.headers]
 * @param {number} [request.timeoutMs]
 * @returns {Promise<{status: number, headers: Headers, text: string, json: any}>}
 */
export async function call(guard, request) {
  const {
    baseUrl, method = 'GET', path, body = null, token = null, headers = {},
    timeoutMs = REQUEST_TIMEOUT_MS,
  } = request;
  const init = { method, headers: { ...headers }, signal: AbortSignal.timeout(timeoutMs) };
  if (token !== null) {
    init.headers.authorization = `Bearer ${token}`;
  }
  if (body !== null) {
    init.headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const response = await fetch(`${baseUrl}${path}`, init);
  guard.check(response.headers, `${method} ${path}`);
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return { status: response.status, headers: response.headers, text, json };
}

/**
 * Load `contracts/sse/channels.json#by_channel` (channel → domain type, §11.2).
 *
 * @returns {Promise<Record<string, string>>}
 * @throws {PreconditionError} When the contract is unreadable (frozen artifact, never invented).
 */
export async function loadByChannel() {
  try {
    const document = JSON.parse(await readFile(CHANNELS_CONTRACT, 'utf8'));
    const mapping = document?.by_channel;
    if (mapping === null || typeof mapping !== 'object' || Object.keys(mapping).length === 0) {
      throw new Error('by_channel missing');
    }
    return mapping;
  } catch (error) {
    throw new PreconditionError(`无法读取 ${CHANNELS_CONTRACT}: ${String(error.message)}`);
  }
}

/**
 * POST a run and collect every SSE frame until the stream closes.
 *
 * @param {NonceGuard} guard
 * @param {object} request
 * @param {string} request.baseUrl
 * @param {string} request.path
 * @param {unknown} request.body
 * @param {string} request.token
 * @param {Record<string, string>} request.byChannel
 * @returns {Promise<{frames: Array<any>, channels: string[], status: number}>}
 */
export async function streamRun(guard, request) {
  const {
    baseUrl, path, body, token, byChannel,
  } = request;
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: {
      accept: 'text/event-stream',
      'content-type': 'application/json',
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  guard.check(response.headers, `POST ${path} (sse)`);
  if (response.status !== 200) {
    const text = await response.text();
    throw new CaseNotGreenError(`SSE run failed: HTTP ${response.status} :: ${text.slice(0, 400)}`, {
      causeCode: 'SSE_HTTP_STATUS',
      details: { status: response.status },
    });
  }
  const parser = new SseStreamParser({ byChannel });
  const reader = response.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    parser.push(Buffer.from(value).toString('utf8'));
  }
  parser.end();
  const frames = parser.frames;
  const channels = [];
  for (const frame of frames) {
    if (frame !== null && frame.type === 'event' && typeof frame.channel === 'string') {
      channels.push(frame.channel);
    }
  }
  return { frames, channels, status: response.status };
}

/**
 * Register a user and create a workspace — the two preconditions every case needs.
 *
 * @param {NonceGuard} guard
 * @param {string} baseUrl
 * @param {string} label
 * @returns {Promise<{token: string, workspaceId: string, username: string}>}
 */
export async function bootstrap(guard, baseUrl, label) {
  const username = `e2e_${label}_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
  const registered = await call(guard, {
    baseUrl,
    method: 'POST',
    path: '/api/v1/auth/register',
    body: {
      username,
      email: `${username}@example.com`,
      password: 'E2e-Passw0rd!23',
      display_name: 'E2E runner',
    },
  });
  if (registered.status !== 201 || typeof registered.json?.data?.access_token !== 'string') {
    throw new CaseNotGreenError(
      `register 期望 201 + access_token，实得 ${registered.status} :: ${registered.text.slice(0, 300)}`,
      { causeCode: 'REGISTER_FAILED', details: { status: registered.status } },
    );
  }
  const token = registered.json.data.access_token;

  const workspace = await call(guard, {
    baseUrl,
    method: 'POST',
    path: '/api/v1/workspaces',
    token,
    body: { name: `E2E WS ${label}`, workspace_type: 'personal' },
  });
  if (workspace.status !== 201 || typeof workspace.json?.data?.id !== 'string') {
    throw new CaseNotGreenError(
      `workspace 期望 201 + id，实得 ${workspace.status} :: ${workspace.text.slice(0, 300)}`,
      { causeCode: 'WORKSPACE_FAILED', details: { status: workspace.status } },
    );
  }
  return { token, workspaceId: workspace.json.data.id, username };
}

/**
 * Create one agent in the workspace (used by the pagination case).
 *
 * @param {NonceGuard} guard
 * @param {string} baseUrl
 * @param {string} token
 * @param {string} workspaceId
 * @param {string} name
 * @returns {Promise<string>} The agent id.
 */
export async function createAgent(guard, baseUrl, token, workspaceId, name) {
  const created = await call(guard, {
    baseUrl,
    method: 'POST',
    path: '/api/v1/agents',
    token,
    body: {
      name, type: 'PRIMARY', workspace_id: workspaceId, description: name,
    },
  });
  if (created.status !== 201 || typeof created.json?.data?.id !== 'string') {
    throw new CaseNotGreenError(
      `agent 期望 201 + id，实得 ${created.status} :: ${created.text.slice(0, 300)}`,
      { causeCode: 'AGENT_FAILED', details: { status: created.status } },
    );
  }
  return created.json.data.id;
}

/**
 * Build a nonce guard labelled for the leg (failures carry fingerprints only).
 *
 * @param {string} nonce
 * @param {string} label
 * @returns {NonceGuard}
 */
export function makeGuard(nonce, label) {
  return new NonceGuard(nonce, { label });
}
