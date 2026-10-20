/**
 * DoD#4 cases 1 and 2 — login and the single-shot 401.
 *
 * Case 1 (`case-1-login`): `POST /api/v1/auth/register` returns 201 + a usable
 * access token, and that token really authorises a read (`GET /api/v1/workspaces`
 * shows the workspace created with it).  Register is used instead of the bootstrap
 * superuser because `admin/123456` is **not** valid in this local database
 * (measured 401 — 裁定 D-3).
 *
 * Case 2 (`case-2-unauthorized`): an unauthenticated read answers **exactly one**
 * 401 with **exactly one** error envelope.  "单飞" is asserted structurally (one
 * `"code":` occurrence in the body, one JSON object, no `errors` array), not by
 * counting retries we cannot see.  The 401 also carries `X-E2E-Nonce` — S-2 says
 * *every* response, and a 401 is a response (§9-2).
 *
 * Both cases check the nonce on every single response they observe (S-2) and the
 * per-file execution counter (S-5).
 */

import assert from 'node:assert/strict';
import test, { after, before } from 'node:test';

import { CaseCounter } from '../../lib/counts.mjs';
import {
  assertRunnerSourcesClean, call, makeGuard, runsLeg, startBackend,
} from '../_harness.mjs';

/** S-5: this file runs 2 of the 4 DoD#4 cases. */
const counter = new CaseCounter(2);
counter.register('case-1-login');
counter.register('case-2-unauthorized');

if (runsLeg('forward')) {
  /** @type {import('../_harness.mjs').BackendContext|null} */
  let backend = null;
  /** @type {import('../../lib/nonce.mjs').NonceGuard|null} */
  let guard = null;

  before(async () => {
    await assertRunnerSourcesClean();
    backend = await startBackend('auth');
    guard = makeGuard(backend.nonce, 'auth');
  });

  after(async () => {
    if (backend !== null) {
      await backend.stop();
    }
    counter.assertComplete();
  });

  test('case-1-login', { timeout: 180_000 }, async () => {
    counter.markExecuted('case-1-login');
    assert.ok(backend !== null && guard !== null, 'backend/guard 未就绪');

    const username = `e2e_login_${Date.now()}`;
    const registered = await call(guard, {
      baseUrl: backend.baseUrl,
      method: 'POST',
      path: '/api/v1/auth/register',
      body: {
        username,
        email: `${username}@example.com`,
        password: 'E2e-Passw0rd!23',
        display_name: 'E2E login',
      },
    });
    assert.equal(registered.status, 201, `register 期望 201，实得 ${registered.status} :: ${registered.text.slice(0, 300)}`);
    const token = registered.json?.data?.access_token;
    assert.equal(typeof token, 'string');
    assert.ok(token.length > 0, 'access_token 不得为空');

    const workspaceName = `E2E login ws ${Date.now()}`;
    const workspace = await call(guard, {
      baseUrl: backend.baseUrl,
      method: 'POST',
      path: '/api/v1/workspaces',
      token,
      body: { name: workspaceName, workspace_type: 'personal' },
    });
    assert.equal(workspace.status, 201, `workspace 期望 201，实得 ${workspace.status}`);

    // The token must actually authorise a read, otherwise "login passed" would only
    // prove that a string was returned.
    const listed = await call(guard, {
      baseUrl: backend.baseUrl,
      path: '/api/v1/workspaces',
      token,
    });
    assert.equal(listed.status, 200, `GET /workspaces 期望 200，实得 ${listed.status}`);
    assert.ok(Array.isArray(listed.json?.data), 'GET /workspaces 的 data 应为数组');
    const names = listed.json.data.map((item) => item?.name);
    assert.ok(
      names.includes(workspaceName),
      `新建 workspace ${workspaceName} 未出现在列表中: ${JSON.stringify(names).slice(0, 300)}`,
    );

    guard.assertCheckedAtLeast(3);
    guard.assertClean();
  });

  test('case-2-unauthorized', { timeout: 180_000 }, async () => {
    counter.markExecuted('case-2-unauthorized');
    assert.ok(backend !== null && guard !== null, 'backend/guard 未就绪');

    const unauthenticated = await call(guard, {
      baseUrl: backend.baseUrl,
      path: '/api/v1/conversations',
      token: null,
    });

    assert.equal(
      unauthenticated.status,
      401,
      `无 token 访问 /conversations 期望 401，实得 ${unauthenticated.status} :: ${unauthenticated.text.slice(0, 300)}`,
    );

    // 单飞: one object, one envelope, no duplicate shell, no error list.
    assert.equal(Array.isArray(unauthenticated.json), false, '401 响应体不应是数组');
    assert.equal(typeof unauthenticated.json, 'object');
    const envelopes = unauthenticated.text.match(/"code"\s*:/g) ?? [];
    assert.equal(envelopes.length, 1, `401 响应壳应恰好一条，实得 ${envelopes.length} 条 :: ${unauthenticated.text.slice(0, 300)}`);
    // The envelope is `{code: str, message: str, data: dict, request_id: str|null}`
    // (schemas/common.py::ErrorResponse) — `code` is an ErrorCode literal, not a number.
    assert.equal(typeof unauthenticated.json.code, 'string');
    assert.ok(unauthenticated.json.code.length > 0, '401 必须带统一错误码（ErrorCode 字面值）');
    assert.ok(
      ['OK', 'SUCCESS', '0'].includes(unauthenticated.json.code) === false,
      `401 的错误码不应是成功码，实得 ${unauthenticated.json.code}`,
    );
    assert.equal(typeof unauthenticated.json.message, 'string');
    assert.ok(unauthenticated.json.message.length > 0, '401 必须有 message');
    assert.equal(
      Object.prototype.hasOwnProperty.call(unauthenticated.json, 'errors'),
      false,
      '401 不应另带 errors 数组（重复壳）',
    );

    guard.assertCheckedAtLeast(1);
    guard.assertClean();
  });
}
