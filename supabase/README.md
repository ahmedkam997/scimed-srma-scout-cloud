# Supabase setup for SciMed Review Scout Cloud

The current production project is:

- Project ref: `vskqiszpjxsmcayuaclo`
- Region: `eu-central-1`
- Plan: Free

The database queue and RLS are already configured on that project.

## Security model

The browser does not create a Supabase Auth account.

Each browser profile generates a random 256-bit device token and sends it as `x-scimed-client-token`. The database stores only its SHA-256 hash. RLS allows a browser to insert and read only jobs associated with that device token.

The GitHub Actions worker uses the public anon API key plus a separate `SCIMED_WORKER_TOKEN`. The database stores only the SHA-256 hash of the worker token. The worker has queue read/update access through RLS and does not receive the Supabase service-role key.

## GitHub Secrets still required

Add these repository Secrets:

- `SCIMED_WORKER_TOKEN`
- `SCIMED_AI_API_KEY` for OpenRouter
- `SEMANTIC_SCHOLAR_API_KEY` optionally

The Supabase URL and anon key are public configuration and are already present in the PWA and worker workflow. The worker defaults to the zero-price OpenRouter free-model router.

## GitHub Pages

In GitHub Settings > Pages, select GitHub Actions as the deployment source. Then manually run the `pages` workflow once.

## Worker

The `discovery-worker` workflow polls every five minutes. It performs a lightweight queue request first. If no job exists, it exits without installing the Python package or PROSPERO CLI.
