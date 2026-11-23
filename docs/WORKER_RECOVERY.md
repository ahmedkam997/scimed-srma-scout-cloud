# SciMed Review Scout: queued-job and free-AI recovery

Updated November 23, 2026. Covers two independent failure modes.

## 1. A job remains QUEUED

GitHub-hosted scheduled workflows may be delayed or skipped. A queued database
row does not mean that the worker has started. The repository has a GitHub
Actions workflow at `.github/workflows/discovery-worker.yml` and a server-side
Supabase Edge Function `wake-discovery-worker` that requests its immediate
execution without exposing a GitHub token to the public browser.

To enable the immediate dispatch path ONCE:

1. Open https://github.com/settings/personal-access-tokens/new
2. Create a fine-grained token belonging to the repository owner.
3. Repository access: select only
   `ahmedkam997/scimed-srma-scout-cloud`.
4. Repository permissions: `Actions: Read and write`.
5. Open the Supabase project dashboard at
   https://supabase.com/dashboard/project/vskqiszpjxsmcayuaclo/functions
   and open **Edge Functions > Secrets**.
6. Add secret name `SCIMED_GITHUB_DISPATCH_TOKEN` with the token value.
   **Do not put the token in web/config.js, GitHub files, screenshots or chat.**
7. The web app's `Start queued worker now` control should then dispatch the
   existing queue job without creating a duplicate. If it fails, open the
   GitHub Actions workflow and select **Run workflow** on `main`.

Verified in incident logs: the Supabase function had a 503 response and a 403
response in the window after the latest Cardiology submission. The precise
reason for each is not observable in the public UI. A missing dispatch
credential is a configured 503 condition and must be checked in the dashboard.
No GitHub token has been supplied to the assistant.

## 2. A job starts, then fails at 5%

The latest real Cardiology job `0673d03c-e6e3-485b-a3e6-caa20b16113a`
was claimed by the worker on November 23 at 07:09 UTC and failed at
07:10 UTC, after no valid candidate JSON was returned from eight limited
free-AI requests. The worker was able to claim and update Supabase rows,
so the problem was AI inference rather than the queue database.

Changes:
- Save real PubMed bibliographic cues BEFORE the AI is called. If inference
  fails, the FAILED job retains a nonqualified evidence checkpoint.
- Show recovered PubMed items and original PubMed links on the failed-job
  card. These are not verified eligible studies or confirmed novel topics.
- Stop making repeated identical calls after two consecutive upstream
  provider failures with zero valid proposals. Show the provider name and
  HTTP code when available without exposing credentials.
- The user may now use `Retry same job`, a device-scoped RLS-protected
  Supabase RPC, **after** AI access has been fixed. No duplicate job is
  created. Retry resets the previous in-progress checkpoint.

To enable the separate free Groq provider, add `GROQ_API_KEY` as a
**GitHub Actions repository secret**, not as a Supabase function secret:
https://github.com/ahmedkam997/scimed-srma-scout-cloud/settings/secrets/actions

The Groq backup cannot run without a valid Groq free-plan API key. The
OpenRouter account's free daily allowance is separate from the Groq account's
allowance; neither service guarantees continuous availability.

## Security and deployment

The client retry RPC only transitions a FAILED row owned by the device token
to QUEUED, and resets status, stage, previous error, and clock fields. All
other client-provided fields are ignored by a PostgreSQL BEFORE UPDATE trigger.
Unowned rows return false. Tests verified owner success, wrong-owner denial,
and prevention of repeated duplicate retries.

Supabase's security advisor returned no findings after migration.
GitHub Actions Python, JavaScript syntax and source tests must pass before
a completed deployment is claimed.

Do not silently auto-retry failed jobs while the free AI accounts are
unavailable, which would expend quota and obscure the root issue.


## Verified on 2026-11-23: dispatch and Groq 403 repairs

- The Edge Function wake-discovery-worker had an HTTP 403 from a privileged
  REST PATCH before it could dispatch GitHub Actions.
- Replaced the PATCH with a SECURITY INVOKER RPC, scimed_request_dispatch.
  Existing device-token RLS restricts the update to an owned queued job.
  The guarded trigger canonicalizes the update to the request timestamp only
  and enforces a 120-second dispatch cooldown.
- Edge Function version 4 was deployed. A live HTTP test with a nonexistent
  job returned HTTP 202 without starting a worker. Transactional tests
  confirmed owner success, wrong-device rejection, and throttling.
- Groq initially returned HTTP 403 to the Python default User-Agent even
  on the public models endpoint. The named SciMed-Review-Scout/1.0 User-Agent
  returned HTTP 200 and an 11-model list. A real request to openai/gpt-oss-20b
  then returned HTTP 200 with valid JSON. A regression test covers the UA.
- Supabase security advisors found no issues.

GitHub Actions verification:
https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45159596498
https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45159953103

This verifies infrastructure and one tiny Groq completion, not an entire
systematic-review discovery. The live smoke test intentionally used an
invalid job ID and did not start the queued Cardiology task.
