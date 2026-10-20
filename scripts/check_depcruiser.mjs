#!/usr/bin/env node
// T1-06 — run the layering rules, and prove they can go red.
//
// Why this wrapper exists (instead of calling depcruise straight from npm)
// -----------------------------------------------------------------------
// `dependency-cruiser` exits 0 for two very different reasons:
//
//   1. it walked the source and found no violation        -> real green
//   2. it walked **nothing** (0 modules) and so found none -> vacuous green
//
// Case 2 is the exact shape of this repo's K-11 defect ("an empty glob is
// vacuously true"). A CI step that calls depcruise directly cannot tell the
// two apart. So this wrapper:
//
//   * requires a **minimum module count** before it will report PASS;
//   * reports **per-rule** results instead of one folded boolean;
//   * has a `--self-test` that **injects a real violation** into a temp file
//     and asserts the gate goes red — then removes it and asserts green again.
//
// Exit codes: 0 pass · 1 violation/vacuous · 2 usage error · 9 self-test failed

import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const REPO_ROOT = resolve(import.meta.dirname, "..");
const CONFIG = join(REPO_ROOT, ".dependency-cruiser.cjs");

// A half-empty scan is indistinguishable from a broken one.  V0.1.0 has 8-ish
// packages plus a full frontend app; 20 is a deliberately *low* floor that a
// real tree clears easily and an accidentally-empty one cannot.
const MIN_MODULES = 20;

const RULES = [
  "no-domain-orm-web",
  "orm-only-in-repositories",
  "no-package-imports-app",
];

function runDepcruise(extraArgs = []) {
  const args = [
    "--config",
    CONFIG,
    "--output-type",
    "json",
    ...extraArgs,
    "packages",
    "apps",
  ];
  // On Windows the entry point is a ``.cmd`` shim, which ``execFileSync`` cannot
  // resolve from PATH without a shell.  Prefer the local shim explicitly and fall
  // back to a shell-resolved name: calling the bare name fails silently with
  // "could not parse JSON output", which reads like a config error but is really
  // a missing executable (measured 2026-10-21).
  const localShim = join(
    REPO_ROOT,
    "node_modules",
    ".bin",
    process.platform === "win32" ? "depcruise.CMD" : "depcruise",
  );
  const command = existsSync(localShim) ? localShim : "depcruise";
  try {
    const stdout = execFileSync(command, args, {
      cwd: REPO_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      shell: process.platform === "win32",
    });
    return { exit: 0, stdout };
  } catch (err) {
    // depcruise signals "violations found" via a non-zero exit; stdout still
    // carries the JSON report we need.
    return { exit: err.status ?? 1, stdout: err.stdout ?? "", stderr: err.stderr ?? "" };
  }
}

function analyse(stdout) {
  let report;
  try {
    report = JSON.parse(stdout);
  } catch {
    return { ok: false, problems: ["could not parse depcruise JSON output"], lines: [] };
  }
  const modules = report?.modules ?? [];
  // Violations live in ``summary.violations`` — NOT in
  // ``modules[].dependencies[].validations``.  Reading the wrong branch made every
  // rule report 0 and turned the baseline green for no reason: a self-test that
  // injects three genuine violations still said "0 violations" (measured
  // 2026-10-21).  That is this repo's K-11 vacuous-pass shape, so the absence of a
  // ``summary`` block is itself an error rather than an empty result.
  const summary = report?.summary;
  const problems = [];
  if (!summary || !Array.isArray(summary.violations)) {
    problems.push(
      "INVALID: depcruise output has no summary.violations — refusing to read absence as 'no violations'"
    );
  }
  const violations = Array.isArray(summary?.violations) ? summary.violations : [];

  if (modules.length < MIN_MODULES) {
    problems.push(
      `INVALID(EMPTY): scanned ${modules.length} modules < ${MIN_MODULES} — ` +
        `a scan this small cannot be a pass`
    );
  }

  const perRule = new Map(RULES.map((r) => [r, 0]));
  const unexpected = new Map();
  for (const violation of violations) {
    const name = violation?.rule?.name ?? "(unnamed)";
    if (perRule.has(name)) {
      perRule.set(name, perRule.get(name) + 1);
    } else {
      unexpected.set(name, (unexpected.get(name) ?? 0) + 1);
    }
  }

  const lines = [
    `scanned modules=${modules.length} (floor ${MIN_MODULES})`,
    `violations total=${violations.length}`,
  ];
  for (const [rule, hits] of perRule) {
    lines.push(`  rule ${rule}: violations=${hits}`);
    if (hits > 0) problems.push(`rule ${rule}: ${hits} violation(s)`);
  }
  for (const [rule, hits] of unexpected) {
    lines.push(`  rule ${rule} (not declared in RULES): violations=${hits}`);
    problems.push(`unexpected rule '${rule}': ${hits} violation(s)`);
  }
  return { ok: problems.length === 0, problems, lines };
}

function selfTest() {
  console.log("[check_depcruiser] self-test");
  let ok = true;

  // -- 1. baseline: the real tree must be green -------------------------------
  const base = analyse(runDepcruise().stdout);
  const basePass = base.ok;
  console.log(`  [${basePass ? "OK" : "FAIL"}] baseline green: ${basePass}`);
  if (!basePass) {
    base.problems.forEach((p) => console.log(`         ${p}`));
    ok = false;
  }

  // -- 2. injection: a genuine violation must turn the gate RED ---------------
  // Each injection targets one rule, so a rule that is silently not matching
  // anything (e.g. a wrong `from` glob) shows up here rather than in prod.
  const injections = [
    {
      rule: "no-domain-orm-web",
      rel: "packages/domain/src/__injected_probe.ts",
      code: "import { sql } from 'drizzle-orm';\nexport const probe = sql;\n",
    },
    {
      rule: "orm-only-in-repositories",
      rel: "packages/logging/src/__injected_probe.ts",
      code: "import { sql } from 'drizzle-orm';\nexport const probe = sql;\n",
    },
    {
      rule: "no-package-imports-app",
      rel: "packages/event/src/__injected_probe.ts",
      code: "import { App } from '../../../apps/web/src/App';\nexport const probe = App;\n",
    },
  ];

  const created = [];
  for (const inj of injections) {
    const abs = join(REPO_ROOT, inj.rel);
    writeFileSync(abs, inj.code, "utf8");
    created.push(abs);
    const res = analyse(runDepcruise().stdout);
    const wentRed = !res.ok && res.problems.some((p) => p.includes(inj.rule));
    console.log(`  [${wentRed ? "OK" : "FAIL"}] injection '${inj.rule}' must go red: ${wentRed}`);
    if (!wentRed) {
      console.log(`         problems seen: ${JSON.stringify(res.problems)}`);
      ok = false;
    }
  }

  for (const abs of created) {
    rmSync(abs, { force: true });
  }

  // -- 3. recovery: removing the injections must restore green ----------------
  const after = analyse(runDepcruise().stdout);
  console.log(`  [${after.ok ? "OK" : "FAIL"}] green restored after cleanup: ${after.ok}`);
  if (!after.ok) {
    after.problems.forEach((p) => console.log(`         ${p}`));
    ok = false;
  }

  console.log(`[check_depcruiser] ${ok ? "PASS" : "FAIL"}`);
  return ok;
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--self-test")) {
    process.exit(selfTest() ? 0 : 9);
  }
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log("usage: node scripts/check_depcruiser.mjs [--self-test]");
    process.exit(0);
  }
  if (!existsSync(CONFIG)) {
    console.log(`[check_depcruiser] FAIL missing config: ${CONFIG}`);
    process.exit(2);
  }

  const res = analyse(runDepcruise().stdout);
  res.lines?.forEach((l) => console.log(`[check_depcruiser] ${l}`));
  res.problems.forEach((p) => console.log(`[check_depcruiser]   PROBLEM: ${p}`));
  console.log(`[check_depcruiser] ${res.ok ? "PASS" : "FAIL"}`);
  process.exit(res.ok ? 0 : 1);
}

main();
