-- Targeted recheck requests are separate from immutable discovery jobs.
-- The browser submits only parent job ID + candidate ID. The worker
-- derives failing sources and PICO from the SAVED completed dossier.
create table if not exists public.scimed_source_rechecks (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.discovery_jobs(id) on delete cascade,
  candidate_id text not null check (char_length(candidate_id) between 1 and 160),
  client_token_hash text not null default private.scimed_client_hash(),
  status text not null default 'QUEUED'
    check(status in ('QUEUED','RUNNING','COMPLETED','FAILED')),
  stage text not null default 'QUEUED',
  progress integer not null default 0 check(progress between 0 and 100),
  message text not null default 'Awaiting targeted source recheck',
  error_text text not null default '',
  result_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);
create index if not exists scimed_recheck_by_owner_date
  on public.scimed_source_rechecks(client_token_hash,created_at desc);
create index if not exists scimed_recheck_queue
  on public.scimed_source_rechecks(status,created_at);
create unique index if not exists scimed_recheck_one_active_per_topic
  on public.scimed_source_rechecks(job_id,candidate_id)
  where status in ('QUEUED','RUNNING');
alter table public.scimed_source_rechecks enable row level security;
alter table public.scimed_source_rechecks force row level security;
revoke all on public.scimed_source_rechecks from public, anon, authenticated;
grant select on public.scimed_source_rechecks to anon,authenticated;
grant insert(job_id,candidate_id) on public.scimed_source_rechecks to anon,authenticated;
grant update(status,stage,progress,message,error_text,result_json,
             updated_at,started_at,completed_at)
      on public.scimed_source_rechecks to anon,authenticated;
create policy scimed_recheck_browser_read
on public.scimed_source_rechecks for select to anon,authenticated
using (
  client_token_hash = private.scimed_client_hash()
  or private.scimed_is_worker()
);
create policy scimed_recheck_browser_queue
on public.scimed_source_rechecks for insert to anon,authenticated
with check (
  status='QUEUED'
  and result_json='{}'::jsonb
  and client_token_hash=private.scimed_client_hash()
  and char_length(coalesce(current_setting('request.headers',true)::jsonb
    ->> 'x-scimed-client-token','')) >=32
  and exists (
    select 1 from public.discovery_jobs j
    where j.id=job_id and j.status='COMPLETED'
    and j.client_token_hash=private.scimed_client_hash()
    and (
      j.result_json #> '{package,options}'
          @> jsonb_build_array(jsonb_build_object('candidate_id',candidate_id))
      or j.result_json #> '{package,provisional_options}'
          @> jsonb_build_array(jsonb_build_object('candidate_id',candidate_id))
    )
  )
);
create policy scimed_recheck_worker_update
on public.scimed_source_rechecks for update to anon,authenticated
using (private.scimed_is_worker())
with check(private.scimed_is_worker());
comment on table public.scimed_source_rechecks is
 'Source-specific bibliographic rechecks; cannot clear scientific eligibility gates or edit the original discovery job.';