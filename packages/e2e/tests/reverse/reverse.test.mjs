/**
 * S-6 · reverse leg — after the process is killed the port must **refuse**.
 *
 * The point is not "an error happened".  It is that the error is *evidence the
 * listener is gone*: only `ECONNREFUSED` / `ENOTFOUND` prove that.  `ETIMEDOUT`
 * proves nothing (the socket may be black-holed) and an assertion mismatch proves
 * the request actually **succeeded** — both are 伪反证 and must exit 31, never 0
 * (`lib/errors.mjs`, K-13).
 *
 * Two modes again:
 *
 * * **orchestrated** (`E2E_BASE_URL` set, `E2E_LEG=reverse`): `run_selfproof.py`
 *   already killed the backend on that port; this file only probes it.
 * * **standalone** (`node --test tests/reverse/reverse.test.mjs`): this file boots
 *   a backend, proves it answers, kills it, and then probes — so the "it was alive
 *   before" half is proven here instead of being assumed.
 *
 * The file registers its test **only** for `E2E_LEG=reverse`, which is why it does
 * not live under `tests/e2e/` (a file with zero tests still counts as one test in
 * `node --test`, which would break the forward leg's exact `4/4` accounting).
 */

import assert from 'node:assert/strict';
import test, { after, before } from 'node:test';

import { CaseCounter } from '../../lib/counts.mjs';
import {
  ALLOWED_RED_CAUSES, classifyRedCause,
} from '../../lib/errors.mjs';
import {
  assertRunnerSourcesClean, isListening, runsLeg, startBackend,
} from '../_harness.mjs';

/** S-6: the reverse leg is one case (it is not one of the 4 DoD#4 cases). */
const counter = new CaseCounter(1);
counter.register('case-r-reverse-refused');

if (runsLeg('reverse')) {
  /** @type {import('../_harness.mjs').BackendContext|null} */
  let backend = null;
  /** @type {boolean} */
  let wasAlive = false;
  /** @type {number} */
  let port = 0;

  before(async () => {
    await assertRunnerSourcesClean();
    backend = await startBackend('reverse');
    port = backend.port;
    if (backend.orchestrated) {
      // The orchestrator killed it already; `true` here would mean the kill failed,
      // which the case below reports as a red.
      wasAlive = true;
    } else {
      // Prove the listener really existed before we killed it.
      assert.equal(await isListening(port), true, `standalone: 端口 ${port} 在 kill 前应处于监听`);
      wasAlive = true;
      await backend.stop();
      backend = { ...backend, stop: async () => {} };
    }
  });

  after(async () => {
    if (backend !== null) {
      await backend.stop();
    }
    counter.assertComplete();
  });

  test('case-r-reverse-refused', { timeout: 180_000 }, async () => {
    counter.markExecuted('case-r-reverse-refused');
    assert.ok(backend !== null, 'backend 未就绪');
    assert.equal(wasAlive, true, '反向段前置：被 kill 的进程此前必须是活的');

    const url = `http://127.0.0.1:${port}`;

    // If the listener is still there, the reverse leg proves nothing: report it as
    // a case-not-green rather than letting the transport error masquerade as proof.
    assert.equal(await isListening(port), false, `端口 ${port} 仍在监听：kill 未生效（EXIT 35 的前置）`);

    /** @type {Array<{label: string, verdict: ReturnType<typeof classifyRedCause>}>} */
    const verdicts = [];
    const probes = [
      { label: 'GET /health', run: () => fetch(`${url}/health`, { signal: AbortSignal.timeout(10_000) }) },
      {
        label: 'GET /api/v1/conversations',
        run: () => fetch(`${url}/api/v1/conversations`, { signal: AbortSignal.timeout(10_000) }),
      },
      {
        label: 'POST /api/v1/auth/register',
        run: () => fetch(`${url}/api/v1/auth/register`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            username: 'never', email: 'never@example.com', password: 'x', display_name: 'never',
          }),
          signal: AbortSignal.timeout(10_000),
        }),
      },
    ];

    for (const probe of probes) {
      let failure = null;
      try {
        const response = await probe.run();
        // A resolved fetch means the listener answered: that is not a red at all.
        failure = new Error(`request succeeded with HTTP ${response.status}: the listener is still up`);
        failure.name = 'AssertionError';
      } catch (error) {
        failure = error;
      }
      const verdict = classifyRedCause(failure);
      verdicts.push({ label: probe.label, verdict });
      assert.equal(
        verdict.allowed,
        true,
        `${probe.label} 的红因不合法: cause=${verdict.cause}（允许 ${ALLOWED_RED_CAUSES.join('/')}；`
        + `ETIMEDOUT 不能证明进程已退出，断言不符说明请求成功了）:: ${verdict.detail}`,
      );
      assert.notEqual(
        verdict.cause,
        'ETIMEDOUT',
        `${probe.label} 红在 ETIMEDOUT：这是伪反证（socket 可能只是被黑洞）`,
      );
    }

    // Every probe must agree: one lucky ECONNREFUSED is not enough.
    assert.equal(verdicts.length, probes.length);
    const causes = new Set(verdicts.map((item) => item.verdict.cause));
    assert.equal(causes.size, 1, `三条探针的红因应一致，实得 ${[...causes].join('/')}`);
  });
}
