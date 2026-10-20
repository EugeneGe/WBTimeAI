/**
 * DoD#4 case 4 — pagination really slices the collection.
 *
 * The case creates **two** agents and then reads `?page=1&page_size=1` and
 * `?page=2&page_size=1`.  The assertion is *identity*, not just "the call
 * returned 200": the two pages must hand back **different objects** (different
 * `id`s) and each must hold exactly one item.  A pagination parameter that is
 * silently ignored would return the same first object twice and must go red —
 * that is why the items are compared by id, not by count alone.
 */

import assert from 'node:assert/strict';
import test, { after, before } from 'node:test';

import { CaseCounter } from '../../lib/counts.mjs';
import {
  assertRunnerSourcesClean, bootstrap, call, createAgent, makeGuard, runsLeg, startBackend,
} from '../_harness.mjs';

/** S-5: this file runs 1 of the 4 DoD#4 cases. */
const counter = new CaseCounter(1);
counter.register('case-4-pagination');

if (runsLeg('forward')) {
  /** @type {import('../_harness.mjs').BackendContext|null} */
  let backend = null;
  /** @type {import('../../lib/nonce.mjs').NonceGuard|null} */
  let guard = null;

  before(async () => {
    await assertRunnerSourcesClean();
    backend = await startBackend('pagination');
    guard = makeGuard(backend.nonce, 'pagination');
  });

  after(async () => {
    if (backend !== null) {
      await backend.stop();
    }
    counter.assertComplete();
  });

  test('case-4-pagination', { timeout: 180_000 }, async () => {
    counter.markExecuted('case-4-pagination');
    assert.ok(backend !== null && guard !== null, 'backend/guard 未就绪');

    const { token, workspaceId } = await bootstrap(guard, backend.baseUrl, 'pagination');
    const first = await createAgent(guard, backend.baseUrl, token, workspaceId, `E2E Page A ${Date.now()}`);
    const second = await createAgent(guard, backend.baseUrl, token, workspaceId, `E2E Page B ${Date.now()}`);
    assert.notEqual(first, second, '两个 agent 的 id 不应相同');

    const pageOne = await call(guard, {
      baseUrl: backend.baseUrl,
      path: '/api/v1/agents?page=1&page_size=1',
      token,
    });
    const pageTwo = await call(guard, {
      baseUrl: backend.baseUrl,
      path: '/api/v1/agents?page=2&page_size=1',
      token,
    });

    assert.equal(pageOne.status, 200, `page=1 期望 200，实得 ${pageOne.status}`);
    assert.equal(pageTwo.status, 200, `page=2 期望 200，实得 ${pageTwo.status}`);
    assert.ok(Array.isArray(pageOne.json?.data), 'page=1 的 data 应为数组');
    assert.ok(Array.isArray(pageTwo.json?.data), 'page=2 的 data 应为数组');
    assert.equal(pageOne.json.data.length, 1, `page_size=1 时 page=1 应恰好 1 条，实得 ${pageOne.json.data.length}`);
    assert.equal(pageTwo.json.data.length, 1, `page_size=1 时 page=2 应恰好 1 条，实得 ${pageTwo.json.data.length}`);

    const firstId = pageOne.json.data[0]?.id;
    const secondId = pageTwo.json.data[0]?.id;
    assert.equal(typeof firstId, 'string');
    assert.equal(typeof secondId, 'string');
    assert.notEqual(
      firstId,
      secondId,
      'page=1 与 page=2 返回了同一个对象：分页参数被忽略（返回相同 id 是假绿）',
    );

    // Determinism: the same page must not shuffle between two calls.
    const pageOneAgain = await call(guard, {
      baseUrl: backend.baseUrl,
      path: '/api/v1/agents?page=1&page_size=1',
      token,
    });
    assert.equal(pageOneAgain.json?.data?.[0]?.id, firstId, 'page=1 两次调用返回了不同对象');

    // Both agents created by this case must be reachable by paging.  The copied
    // database already holds rows from earlier probe runs, so the case pages until
    // it has seen its own two ids instead of assuming they sit on pages 1 and 2.
    const seen = new Set([firstId, secondId]);
    let pagesWalked = 0;
    for (let page = 1; page <= 6; page += 1) {
      const listed = await call(guard, {
        baseUrl: backend.baseUrl,
        path: `/api/v1/agents?page=${page}&page_size=1`,
        token,
      });
      assert.equal(listed.status, 200, `page=${page} 期望 200，实得 ${listed.status}`);
      assert.ok(Array.isArray(listed.json?.data), `page=${page} 的 data 应为数组`);
      if (listed.json.data.length === 0) {
        break; // past the end of the collection — not a failure
      }
      assert.equal(listed.json.data.length, 1, `page_size=1 时 page=${page} 应恰好 1 条`);
      pagesWalked += 1;
      seen.add(listed.json.data[0]?.id);
    }
    assert.ok(pagesWalked >= 3, `前 6 页至少应走到 3 页（库内已有行），实得 ${pagesWalked}`);
    assert.ok(seen.has(first), `本用例创建的 agent ${first} 未能在前 6 页中被列出`);
    assert.ok(seen.has(second), `本用例创建的 agent ${second} 未能在前 6 页中被列出`);

    guard.assertCheckedAtLeast(6);
    guard.assertClean();
  });
}
