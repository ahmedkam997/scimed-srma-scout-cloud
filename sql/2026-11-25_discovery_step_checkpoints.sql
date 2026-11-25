create table if not exists public.scimed_discovery_steps (
  job_id uuid not null references public.discovery_jobs(id) on delete cascade,
  step_key text not null check (length(step_key) between 1 and 180),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  updated_at timestamptz not null default now(),
  primary key (job_id, step_key)
);
alter table public.scimed_discovery_steps enable row level security;
revoke all on public.scimed_discovery_steps from public, anon, authenticated;
grant select,insert,update on public.scimed_discovery_steps to anon,authenticated;
create policy discovery_step_worker_read on public.scimed_discovery_steps for select to anon,authenticated
  using ((select private.scimed_is_worker()));
create policy discovery_step_worker_insert on public.scimed_discovery_steps for insert to anon,authenticated
  with check ((select private.scimed_is_worker()) and exists (select 1 from public.discovery_jobs j where j.id=job_id and j.status='RUNNING'));
create policy discovery_step_worker_update on public.scimed_discovery_steps for update to anon,authenticated
  using ((select private.scimed_is_worker()) and exists (select 1 from public.discovery_jobs j where j.id=job_id and j.status='RUNNING'))
  with check ((select private.scimed_is_worker()) and exists (select 1 from public.discovery_jobs j where j.id=job_id and j.status='RUNNING'));
notify pgrst, 'reload schema';
