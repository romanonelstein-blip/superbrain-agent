import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { GitHubCliProvider } from '../dist/core/github.js';

const dir = mkdtempSync(join(tmpdir(), 'superbrain-gh-'));
const oldPath = process.env.PATH;
writeFileSync(join(dir, 'gh'), `#!/usr/bin/env node
const args = process.argv.slice(2);
if (args.includes('--show-token')) { console.error('SECRET_SENTINEL'); process.exit(1); }
if (args[0] === '--version') { console.log('gh version 2.80.0'); process.exit(0); }
process[process.env.GH_TEST_STREAM || 'stdout'].write(process.env.GH_TEST_OUTPUT || '');
process.exit(Number(process.env.GH_TEST_EXIT || 0));
`, { mode: 0o755 });
process.env.PATH = `${dir}:${oldPath}`;
const provider = new GitHubCliProvider();

try {
  await test('GitHub authentication diagnostics never request or expose tokens', async t => {
    for (const stream of ['stdout', 'stderr']) {
      await t.test(`reads account and host from ${stream}`, async () => {
        process.env.GH_TEST_STREAM = stream;
        process.env.GH_TEST_EXIT = '0';
        process.env.GH_TEST_OUTPUT = 'github.com\n  ✓ Logged in to github.com account romano (keyring)\n';
        const status = await provider.getAuthStatus();
        assert.equal(status.isLoggedIn, true);
        assert.equal(status.username, 'romano');
        assert.deepEqual(status.activeHosts, ['github.com']);
      });
    }
    await t.test('supports legacy status output', async () => {
      process.env.GH_TEST_OUTPUT = 'Logged in to github.example.com as romano (keyring)';
      assert.equal((await provider.getAuthStatus()).username, 'romano');
    });
    await t.test('failed authentication returns no raw process output', async () => {
      process.env.GH_TEST_EXIT = '1';
      process.env.GH_TEST_OUTPUT = 'SECRET_SENTINEL';
      const status = await provider.getAuthStatus();
      assert.equal(status.isLoggedIn, false);
      assert.equal(status.isAvailable, true);
      assert.ok(!JSON.stringify(status).includes('SECRET_SENTINEL'));
      assert.match(status.error, /gh auth login/);
    });
    await t.test('unrecognized output does not claim login', async () => {
      process.env.GH_TEST_EXIT = '0';
      process.env.GH_TEST_OUTPUT = 'unknown response';
      const status = await provider.getAuthStatus();
      assert.equal(status.isLoggedIn, false);
      assert.ok(status.error);
    });
    await t.test('missing CLI gives installation guidance', async () => {
      process.env.PATH = dir + '/missing';
      const status = await provider.getAuthStatus();
      assert.equal(status.isAvailable, false);
      assert.match(status.error, /Install/);
    });
  });
} finally {
  process.env.PATH = oldPath;
  for (const key of ['GH_TEST_STREAM', 'GH_TEST_EXIT', 'GH_TEST_OUTPUT']) delete process.env[key];
  rmSync(dir, { recursive: true, force: true });
}
