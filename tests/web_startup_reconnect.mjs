import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const app = readFileSync('web/app.js', 'utf8');
const html = readFileSync('web/index.html', 'utf8');
const sw = readFileSync('web/sw.js', 'utf8');
const start = app.indexOf('async function withTimeout(');
const end = app.indexOf('function deviceToken()', start);
assert.ok(start > 0 && end > start, 'Startup/timeout helpers must be present');
const helpers = app.slice(start, end);

function isolated(mockFetch, timeout = 18) {
  return runInNewContext(
    'const CLOUD_REQUEST_TIMEOUT_MS = ' + timeout + ';\n' +
    helpers + '\n({ withTimeout, cloudFetch });',
    { fetch: mockFetch, setTimeout, clearTimeout, AbortController }
  );
}

test('startup does not depend on an eager CDN import', () => {
  assert.ok(!app.trimStart().startsWith('import '), 'App must render diagnostics before loading the SDK');
  assert.ok(app.includes('https://esm.sh/@supabase/supabase-js@2.119.2?bundle'));
  assert.ok(app.includes('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.119.2/+esm'));
  assert.ok(app.includes('data-reconnect'), 'Failed connection must show retry');
  assert.ok(html.includes('reloadCloudApp'), 'Independent HTML startup watchdog must be active');
  assert.ok(html.includes('durable-resume'));
  assert.ok(sw.includes('scimed-review-scout-v40'));
});

test('startup timeout produces a recoverable error instead of waiting forever', async () => {
  const { withTimeout } = isolated(() => {});
  assert.equal(await withTimeout(Promise.resolve('ok'), 20, 'timeout'), 'ok');
  await assert.rejects(withTimeout(new Promise(() => {}), 10, 'SDK timeout'), /SDK timeout/);
});

test('network timeout aborts the underlying request and reports a useful message', async () => {
  let aborted = false;
  const mockFetch = (_url, opts) => new Promise((_, reject) => {
    opts.signal.addEventListener('abort', () => {
      aborted = true;
      reject(new Error('native abort'));
    }, { once: true });
  });
  const { cloudFetch } = isolated(mockFetch, 10);
  await assert.rejects(cloudFetch('https://example.test'), /Cloud request timed out/);
  assert.equal(aborted, true);
});

test('a successful cloud response passes through unchanged', async () => {
  const response = { status: 200, ok: true };
  const { cloudFetch } = isolated(async () => response);
  assert.equal(await cloudFetch('https://example.test'), response);
});

test('queue polling excludes large reports and deduplicates requests', () => {
  const load = app.slice(app.indexOf('async function loadJobs()'), app.indexOf('function safeEvidenceLink('));
  assert.ok(load.includes('.select(JOB_STATUS_FIELDS)'));
  assert.ok(load.includes('if (jobsRefresh) return jobsRefresh'));
  assert.ok(load.includes(".select('id,updated_at,result_json,error_text').eq('id', jobId).single()"));
  assert.ok(!load.includes(".select('*')"));
});
