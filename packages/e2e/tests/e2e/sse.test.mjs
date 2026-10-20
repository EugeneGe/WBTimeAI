/**
 * DoD#4 case 3 — the SSE channel matrix, observed frame by frame.
 *
 * Acceptance (§1.2.2, fixed): three scenarios whose channel union must contain the
 * 9 core channels, each seen at least once in a **real** stream.  This file drives
 * two of the three scenarios on one boot:
 *
 * | scenario  | how it is driven | channels |
 * |-----------|------------------|----------|
 * | `s-main`  | scripted provider: one tool call, then a final answer | agent.started, agent.thinking, message.delta, tool.started, tool.completed, agent.completed |
 * | `s-error` | a second run on the same agent: the provider keeps asking for a tool, `max_iterations` runs out ⇒ `error_type=MAX_ITERATIONS` ⇒ `agent.failed` ⇒ `agent.error` | agent.error |
 * | `s-mcp`   | **not driven** — needs an MCP transport double (`register_mcp_server` + transport stub) that this version does not install | mcp.started, mcp.completed |
 *
 * Honesty boundary (§1.2.2 «诚实边界»): `s-mcp` is therefore **未验证（依赖不可得）**.
 * The case stays green because it asserts exactly the *observed* scenarios, and it
 * asserts that the **only** missing channels are the two `mcp.*` ones.  It must
 * never be reported as "9 条实帧已验证": with `s-mcp` unavailable the observed
 * coverage is **7/9**, and `03-台账/真后端自证.md` records 7/9 + the reason.
 * Declaring `SCENARIO_CHANNELS['s-mcp']` complete without frames would be exactly
 * the fake green this version exists to kill.
 */

import assert from 'node:assert/strict';
import test, { after, before } from 'node:test';

import { CaseCounter } from '../../lib/counts.mjs';
import {
  CORE_CHANNELS, SCENARIO_CHANNELS, assertScenarioCoverage, coverageMatrix, formatCoverageLine,
} from '../../lib/sse.mjs';
import {
  assertRunnerSourcesClean, bootstrap, call, createAgent, loadByChannel, makeGuard,
  runsLeg, startBackend, streamRun,
} from '../_harness.mjs';

/** S-5: this file runs 1 of the 4 DoD#4 cases. */
const counter = new CaseCounter(1);
counter.register('case-3-sse-channels');

if (runsLeg('forward')) {
  /** @type {import('../_harness.mjs').BackendContext|null} */
  let backend = null;
  /** @type {import('../../lib/nonce.mjs').NonceGuard|null} */
  let guard = null;
  /** @type {Record<string, string>} */
  let byChannel = {};

  before(async () => {
    await assertRunnerSourcesClean();
    backend = await startBackend('sse');
    guard = makeGuard(backend.nonce, 'sse');
    byChannel = await loadByChannel();
  });

  after(async () => {
    if (backend !== null) {
      await backend.stop();
    }
    counter.assertComplete();
  });

  test('case-3-sse-channels', { timeout: 300_000 }, async (t) => {
    counter.markExecuted('case-3-sse-channels');
    assert.ok(backend !== null && guard !== null, 'backend/guard 未就绪');
    const { baseUrl } = backend;

    const { token, workspaceId } = await bootstrap(guard, baseUrl, 'sse');

    // --- the bookkeeping rows the probe proved are required -----------------
    const provider = await call(guard, {
      baseUrl,
      method: 'POST',
      path: '/api/v1/models/providers',
      token,
      body: {
        name: 'e2e-openai',
        provider_type: 'openai',
        endpoint: 'https://api.openai.com/v1',
        workspace_id: workspaceId,
      },
    });
    assert.equal(provider.status, 201, `provider 期望 201，实得 ${provider.status} :: ${provider.text.slice(0, 300)}`);
    const providerId = provider.json.data.id;

    const model = await call(guard, {
      baseUrl,
      method: 'POST',
      path: `/api/v1/models/providers/${providerId}/models`,
      token,
      body: { name: 'gpt-e2e', model_type: 'CHAT', context_window: 128000 },
    });
    assert.equal(model.status, 201, `model 期望 201，实得 ${model.status} :: ${model.text.slice(0, 300)}`);

    const tools = await call(guard, { baseUrl, path: '/api/v1/tools', token });
    assert.equal(tools.status, 200, `tools 期望 200，实得 ${tools.status}`);
    assert.ok(Array.isArray(tools.json?.data), 'tools 的 data 应为数组');

    const agentId = await createAgent(guard, baseUrl, token, workspaceId, `E2E SSE ${Date.now()}`);
    const published = await call(guard, {
      baseUrl,
      method: 'POST',
      path: `/api/v1/agents/${agentId}/publish`,
      token,
      body: {
        system_prompt: 'You are a helpful coding agent.',
        // `scripted` / `scripted-1` are registered in-process by the launcher.
        model_config: { provider: 'scripted', model: 'scripted-1' },
        runtime_config: { max_iterations: 3 },
        tools: [{ tool_id: 'shell', permission_scope: {}, enabled: true }],
      },
    });
    assert.equal(published.status, 201, `publish 期望 201，实得 ${published.status} :: ${published.text.slice(0, 400)}`);

    // --- s-main ------------------------------------------------------------
    const mainRun = await streamRun(guard, {
      baseUrl,
      path: `/api/v1/agents/${agentId}/run`,
      body: { message: 'hi', workspace_id: workspaceId },
      token,
      byChannel,
    });
    assert.ok(mainRun.frames.length > 0, 's-main 未收到任何 SSE 帧');
    assertScenarioCoverage('s-main', mainRun.channels);

    // --- s-error -----------------------------------------------------------
    const errorRun = await streamRun(guard, {
      baseUrl,
      path: `/api/v1/agents/${agentId}/run`,
      body: { message: 'again', workspace_id: workspaceId },
      token,
      byChannel,
    });
    assert.ok(errorRun.frames.length > 0, 's-error 未收到任何 SSE 帧');
    assertScenarioCoverage('s-error', errorRun.channels);

    // --- the union: only the mcp pair may be missing ----------------------
    const observed = new Set([...mainRun.channels, ...errorRun.channels]);
    const matrix = coverageMatrix(observed);
    t.diagnostic(formatCoverageLine(matrix));
    t.diagnostic(`observed=${JSON.stringify([...observed].sort())}`);

    const nonMcp = CORE_CHANNELS.filter((channel) => !SCENARIO_CHANNELS['s-mcp'].includes(channel));
    const missingNonMcp = nonMcp.filter((channel) => !observed.has(channel));
    assert.deepEqual(
      missingNonMcp,
      [],
      `非 mcp 通道必须全部实测到，缺: ${missingNonMcp.join(',')} :: ${formatCoverageLine(matrix)}`,
    );
    const unexpected = matrix.missing.filter((channel) => !SCENARIO_CHANNELS['s-mcp'].includes(channel));
    assert.deepEqual(
      unexpected,
      [],
      `缺失通道只允许是 s-mcp 的两条（未验证），实得: ${unexpected.join(',')}`,
    );
    assert.ok(
      matrix.observed >= nonMcp.length,
      `实测通道数 ${matrix.observed} 少于非 mcp 通道数 ${nonMcp.length}`,
    );

    guard.assertCheckedAtLeast(9);
    guard.assertClean();
  });
}
