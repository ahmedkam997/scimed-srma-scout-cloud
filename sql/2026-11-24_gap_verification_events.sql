-- SciMed Review Scout: browser-scoped, append-only source adjudication history.
-- Device token ownership is inherited from discovery_jobs. This is NOT
-- user authentication or a scientific eligibility/novelty decision.
create table if not exists public.scimed_gap_verification_events (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.discovery_jobs(id) on delete cascade,
  candidate_id text not null check (char_length(candidate_id) between 1 and 160),
  record_key text not null check (char_length(record_key) between 3 and 500),
  record_type text not null check (record_type in ('review','registration')),
  title_at_adjudication text not null check (char_length(title_at_adjudication) between 1 and 500),
  source text not null check (char_length(source) between 1 and 160),
  decision text not null check (decision in (
    'NEEDS_FULL_TEXT', 'POTENTIAL_OVERLAP',
    'DOCUMENTED_OVERLAP', 'DOCUMENTED_NON_OVERLAP'
  )),
  evidence_url text not null check (
    char_length(evidence_url) <= 1500 and
    evidence_url ~ '^https://[^[:space:]]+$'
  ),
  documented_last_search_date date,
  rationale text not null check (char_length(rationale) between 15 and 1800),
  client_token_hash text not null default private.scimed_client_hash(),
  created_at timestamptz not null default clock_timestamp(),
  constraint gap_search_date_is_documented_past check (
    documented_last_search_date is null or (
      record_type = 'review'
      and documented_last_search_date >= date '1900-01-01'
      and documented_last_search_date <= current_date
    )
  )
);
create index if not exists scimed_gap_events_by_job
  on public.scimed_gap_verification_events(job_id, candidate_id, created_at, id);
alter table public.scimed_gap_verification_events enable row level security;
alter table public.scimed_gap_verification_events force row level security;

-- Grant no UPDATE or DELETE: corrections are new source-linked events.
revoke all on table public.scimed_gap_verification_events from public, anon, authenticated;
grant select on public.scimed_gap_verification_events to anon, authenticated;
grant insert (
  id, job_id, candidate_id, record_key, record_type,
  title_at_adjudication, source, decision, evidence_url,
  documented_last_search_date, rationale
) on public.scimed_gap_verification_events to anon, authenticated;

create policy gap_events_read_same_browser
on public.scimed_gap_verification_events for select to anon, authenticated
using (
  client_token_hash = private.scimed_client_hash()
  and exists (
    select 1 from public.discovery_jobs j
    where j.id = job_id
      and j.client_token_hash = private.scimed_client_hash()
      and j.status = 'COMPLETED'
  )
);

create policy gap_events_insert_own_completed_dossier
on public.scimed_gap_verification_events for insert to anon, authenticated
with check (
  client_token_hash = private.scimed_client_hash()
  and char_length(coalesce((
    current_setting('request.headers', true)::jsonb ->> 'x-scimed-client-token'
  ), '')) >= 32
  and exists (
    select 1 from public.discovery_jobs j
    where j.id = job_id
      and j.client_token_hash = private.scimed_client_hash()
      and j.status = 'COMPLETED'
      and (
        j.result_json #> '{package,options}'
          @> jsonb_build_array(jsonb_build_object('candidate_id', candidate_id))
        or j.result_json #> '{package,provisional_options}'
          @> jsonb_build_array(jsonb_build_object('candidate_id', candidate_id))
      )
  )
);

comment on table public.scimed_gap_verification_events is
  'Browser device-token scoped append-only human evidence notes. Never a scientific qualification gate or independent eligible study count.';
