# SciMed Review Scout Cloud: queue reliability and free-AI recovery

2026-11-23. Scope: existing public GitHub Pages, Supabase queue, GitHub Actions worker.

## Incident: Cardiology job at 0% (QUEUED)

The job created on 2026-11-23 06:52:22 UTC remained QUEUED at the
user's 09:00 screenshot, although GitHub's workflow had a nominal
five-minute schedule. The last genuine `schedule` run was at
2026-11-23 01:08 UTC. Subsequent worker executions were `push`
or manual triggers, showing that the queue was not reliably triggered.

GitHub documents scheduled events as best-effort and sometimes delayed or
dropped. Changing the cron to an offset minute may resume it but is not
a guaranteed delivery mechanism.

## What was built

An Edge Function named `wake-discovery-worker` is deployed with
`verify_jwt=true`, and its versioned source lives at
`supabase/functions/wake-discovery-worker/index.ts`.

- Browser creates the queued job normally.
- It calls the Edge Function with that job ID and its 256-bit browser token.
- The function SHA-256 hashes the token and atomically checks the saved
  job owner, status QUEUED and a two-minute dispatch cooldown.
- Only after successful ownership/queue validation does it POST
  GitHub's workflow dispatch API.
- The PAT stays in Supabase Function Secrets, never in a web bundle.
- Github's workflow has an alternate `repository_dispatch` trigger and
  an off-minute scheduled cron as fallback.
- Existing queued jobs get a Start queued worker now button and the
  GitHub manual workflow link.
- Response failures do not delete/duplicate the queued job.
- The worker continues to claim only QUEUED jobs transactionally via
  a status-conditional REST update.

## One-time setup still REQUIRED

The server function is deployed but live tests currently return
`configuration_required` because no GitHub dispatch token exists in
Supabase Functions Secrets.

1. Sign in to GitHub > Settings > Developer settings > Personal access
   tokens > Fine-grained tokens.
2. Limit repository access to `ahmedkam997/scimed-srma-scout-cloud`.
3. Grant repository permission `Actions: Read and write`; no other
   repository write permissions should be necessary for workflow_dispatch.
4. Generate a token with an appropriate expiry.
5. In the Supabase project `vskqiszpjxsmcayuaclo`, navigate to
   Edge Functions > Secrets and store exactly:
   `SCIMED_GITHUB_DISPATCH_TOKEN` = the GitHub fine-grained PAT.
6. Do not put this secret in GitHub public files, web/config.js,
   localStorage, screenshots or a chat message.
7. Test Start queued worker now for a newly QUEUED job and verify the
   status moves to RUNNING. The token is used only for workflow dispatch.

Official GitHub workflow API permissions:
https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event

Supabase Edge Function Secrets:
https://supabase.com/docs/guides/functions/secrets

## Second independent failure: AI at 5%

The user's previously QUEUED job was claimed by GitHub worker run
https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45129064926
but FAILED at 5% after 8 bounded attempts without valid JSON.

Live minimal provider tests:
- OpenRouter `openrouter/free`: HTTP 429
- Groq `openai/gpt-oss-20b`: HTTP 403

The exact Groq 403 reason requires a permission/status diagnostic
before changing the production model. Official Groq docs explain that
models restricted by organization or project policy produce 403:
https://console.groq.com/docs/model-permissions

The GitHub Actions secrets `SCIMED_AI_API_KEY` and `GROQ_API_KEY`
are separate from the Supabase dispatch token. The workflow cannot
generate viable topics until at least one inference provider responds
with valid JSON. Do not mark a 5% model failure as a failed scientific
topic audit or a missing primary-study evidence base.

## Verification

- Supabase Edge Function deployed successfully, JWT verification enabled.
- A real unauthenticated-device invocation returned 403.
- A valid-shaped but unconfigured dispatch invocation returned 503
  `configuration_required` without exposing secrets.
- Python and JavaScript GitHub tests passed.
- Push-triggered GitHub worker claimed the user's existing queued job.
- Automatic future dispatch **not yet verified** pending the GitHub
  fine-grained token in Supabase Function Secrets.
- No new Cardiology job was created for testing.
