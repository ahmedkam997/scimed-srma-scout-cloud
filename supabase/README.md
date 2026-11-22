# Supabase setup for SciMed Review Scout Cloud

1. Create one Supabase Free project.
2. Open SQL Editor and run `supabase/schema.sql`.
3. In Authentication settings, enable Anonymous Sign-Ins.
4. In GitHub repository Variables, add:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
5. In GitHub repository Secrets, add:
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SCIMED_AI_ENDPOINT`
   - `SCIMED_AI_MODEL`
   - `SCIMED_AI_API_KEY` when your provider needs one
   - `SEMANTIC_SCHOLAR_API_KEY` optionally
6. In GitHub Settings > Pages, choose GitHub Actions as the deployment source.
7. Run the `pages` workflow once, or push a commit.
8. Run `discovery-worker` manually once to validate the queue. The scheduled worker also polls every five minutes.

The browser only receives the public Supabase URL and anon key. The Supabase service-role key and AI credentials stay in GitHub Secrets.

Anonymous sign-in persists in the same browser profile. A later account-login phase can add cross-device identity without changing the job schema.
