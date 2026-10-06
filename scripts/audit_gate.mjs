/**
 * npm audit gate — fails on any production dependency vulnerability that is
 * not explicitly documented below.
 *
 * CI runs this instead of a bare `npm audit --omit=dev` because `npm audit` has
 * no per-advisory ignore flag: one unfixable transitive finding would otherwise
 * either block every push forever or force someone to weaken the whole gate.
 * This keeps the gate strict for everything else — the allow-list is matched on
 * the exact package AND advisory id, so a *new* advisory in an allow-listed
 * package still fails the build.
 *
 * Local use:  node scripts/audit_gate.mjs
 */

import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const ALLOWED = [
  {
    package: 'sprintf-js',
    advisory: 'GHSA-hp3w-g68c-fv3c',
    reason:
      'DoS via unbounded precision specifiers. Chain: @tensorflow/tfjs → argparse → sprintf-js. ' +
      'No fixed version exists — every sprintf-js release is flagged, and npm\'s only suggested ' +
      'fix downgrades @tensorflow/tfjs to 2.1.0 (a seven-year-old breaking major). argparse is ' +
      'tfjs\'s Node-side CLI tooling, verified absent from the built browser bundle (dist/assets), ' +
      'so the vulnerable parser never ships to a browser. Re-check when tfjs drops argparse.',
  },
];

/** GHSA id from an advisory URL, e.g. .../advisories/GHSA-hp3w-g68c-fv3c */
function advisoryId(advisory) {
  const url = String(advisory.url ?? '');
  const match = url.match(/\/advisories\/([A-Z]+-[a-z0-9-]+)$/i);
  return match ? match[1] : url;
}

/**
 * Pure decision function over `npm audit --json` output.
 *
 * Returns { ok, disallowed, accepted, chains }. An allow-listed package whose
 * report carries a DIFFERENT advisory id is disallowed — the exemption is per
 * advisory, not per package.
 *
 * npm lists the whole dependency path of a finding: the vulnerable package
 * carries the advisory object, while its dependents (argparse, tfjs) carry only
 * bare names in `via`. Those chain entries are the SAME finding, so they are
 * reported for visibility but never gated — otherwise one advisory would fail
 * the build three times.
 */
export function evaluateAudit(report, allowed = ALLOWED) {
  const vulnerabilities = report?.vulnerabilities ?? {};
  const disallowed = [];
  const accepted = [];
  const chains = [];

  for (const [name, entry] of Object.entries(vulnerabilities)) {
    const via = entry.via ?? [];
    const advisories = via.filter((item) => item && typeof item === 'object' && item.url);

    if (advisories.length === 0) {
      // No advisory of its own — this entry is a dependent in someone else's
      // dependency path, already gated at the package that owns the advisory.
      chains.push({ package: name, severity: entry.severity, dependsOn: via.join(', ') });
      continue;
    }

    for (const advisory of advisories) {
      const finding = {
        package: name,
        advisory: advisoryId(advisory),
        severity: entry.severity,
        title: advisory.title ?? '',
      };
      const exemption = allowed.find(
        (rule) => rule.package === finding.package && rule.advisory === finding.advisory
      );
      if (exemption) {
        accepted.push({ ...finding, reason: exemption.reason });
      } else {
        disallowed.push(finding);
      }
    }
  }

  return { ok: disallowed.length === 0, disallowed, accepted, chains };
}

/** Run the audit and apply the allow-list. Returns a process exit code. */
export function main() {
  const run = spawnSync('npm', ['audit', '--omit=dev', '--json'], {
    encoding: 'utf8',
    shell: process.platform === 'win32',
  });

  // npm exits non-zero purely because vulnerabilities were found; only an
  // unparsable report is a gate error.
  let report;
  try {
    report = JSON.parse(run.stdout ?? '');
  } catch {
    console.error('npm audit gate: could not parse npm audit --json output.');
    console.error(run.stderr || run.stdout || '(no output)');
    return 1;
  }

  const { ok, disallowed, accepted, chains } = evaluateAudit(report);

  for (const item of accepted) {
    console.log(
      `accepted (documented): ${item.package} — ${item.advisory} [${item.severity}]`
    );
    console.log(`  ${item.reason}`);
  }

  for (const item of chains) {
    console.log(`dependency path (not a separate finding): ${item.package} ← ${item.dependsOn}`);
  }

  if (ok) {
    console.log(
      `npm audit gate: ${accepted.length} documented exception(s), 0 blocking findings.`
    );
    return 0;
  }

  console.error('npm audit gate: blocking production dependency findings:');
  for (const item of disallowed) {
    console.error(`  ${item.package} — ${item.advisory} [${item.severity}] ${item.title}`);
  }
  console.error(
    '\nFix them, or — if a finding is genuinely unfixable and not in the bundle — ' +
      'document it in ALLOWED in scripts/audit_gate.mjs with a reason.'
  );
  return 1;
}

// Compare as file URLs: import.meta.url is percent-encoded, so a repo path
// containing spaces ("/Volumes/Volumn 1/...") never matches the raw
// process.argv[1] string — which would make the gate exit 0 without auditing.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}