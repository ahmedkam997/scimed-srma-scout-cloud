-- Owner-scoped recovery; security invoker and existing guarded transition.
create or replace function private.scimed_cancel_guard()
returns trigger language plpgsql security invoker set search_path = ''
as $$
begin
  if current_user in ('postgres','service_role') or private.scimed_is_worker() then
    return new;
  end if;
  if old.client_token_hash is distinct from private.scimed_client_hash() then
    raise exception 'Unauthorized discovery job status transition';
  end if;

  if old.status in ('QUEUED','RUNNING') and new.status='CANCELLED' then
    new := old;
    new.status := 'CANCELLED';
    new.stage := 'CANCELLED';
    new.message := 'Cancelled from this device. Worker stops at the next safe checkpoint.';
    new.error_text := '';
    new.completed_at := clock_timestamp();
    new.updated_at := clock_timestamp();
    return new;
  elsif old.status='FAILED' and new.status='QUEUED' then
    new := old;
    new.status := 'QUEUED';
    new.stage := 'QUEUED';
    new.progress := 0;
    new.message := 'Retry queued from this device; awaiting a free AI provider and worker.';
    new.error_text := '';
    new.result_json := '{}'::jsonb;
    new.started_at := null;
    new.completed_at := null;
    new.dispatch_requested_at := null;
    new.updated_at := clock_timestamp();
    return new;
  elsif old.status='COMPLETED' and new.status='QUEUED'
    and length(coalesce(current_setting('request.headers', true)::jsonb ->> 'x-scimed-client-token','')) >= 32
    and old.result_json #>> '{run_summary,mode}' = 'RCT_FIRST_V1'
    and old.result_json #> '{run_summary,resume_eligible}' = 'true'::jsonb
    and old.completed_at <= clock_timestamp() - interval '10 minutes'
    and not exists (select 1 from public.discovery_jobs j where j.client_token_hash=old.client_token_hash
      and j.id<>old.id and j.specialty=old.specialty and j.question_type=old.question_type and j.status in ('QUEUED','RUNNING')) then
    new := old;
    new.status := 'QUEUED';
    new.stage := 'QUEUED';
    new.progress := 0;
    new.message := 'Resume queued; saved evidence and the last report are retained.';
    new.error_text := '';
    new.started_at := null;
    new.completed_at := null;
    new.dispatch_requested_at := null;
    new.updated_at := clock_timestamp();
    return new;
  elsif old.status='QUEUED' and new.status='QUEUED'
    and new.dispatch_requested_at is distinct from old.dispatch_requested_at
    and (old.dispatch_requested_at is null
      or old.dispatch_requested_at < clock_timestamp() - interval '120 seconds') then
    new := old;
    new.dispatch_requested_at := clock_timestamp();
    new.updated_at := clock_timestamp();
    return new;
  end if;

  raise exception 'Unauthorized discovery job status transition';
end;
$;


-- New client inserts cannot fabricate completed reports or resume flags.
drop policy if exists "clients_insert_own_discovery_jobs" on public.discovery_jobs;
create policy "clients_insert_own_discovery_jobs" on public.discovery_jobs
for insert to anon,authenticated
with check (client_token_hash=private.scimed_client_hash() and status='QUEUED'
  and result_json='{}'::jsonb and started_at is null and completed_at is null);
drop policy if exists "clients_resume_own_rct_jobs" on public.discovery_jobs;
create policy "clients_resume_own_rct_jobs" on public.discovery_jobs
for update to anon,authenticated
using (client_token_hash=private.scimed_client_hash() and status='COMPLETED'
  and length(coalesce(current_setting('request.headers', true)::jsonb ->> 'x-scimed-client-token','')) >= 32
  and result_json #>> '{run_summary,mode}'='RCT_FIRST_V1'
  and result_json #> '{run_summary,resume_eligible}'='true'::jsonb
  and completed_at <= clock_timestamp()-interval '10 minutes')
with check (client_token_hash=private.scimed_client_hash() and status='QUEUED');

create or replace function public.scimed_resume_rct_job(p_job_id uuid)
returns boolean language plpgsql security invoker set search_path=''
as $$
declare v_hash text; v_updated integer;
begin
  if length(coalesce(current_setting('request.headers',true)::jsonb ->> 'x-scimed-client-token','')) < 32 then return false; end if;
  v_hash := private.scimed_client_hash();
  if v_hash is null or length(v_hash)<>64 then return false; end if;
  -- Serialize concurrent resume requests for this device (same transaction).
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_hash,0));
  update public.discovery_jobs d set status='QUEUED'
   where d.id=p_job_id and d.client_token_hash=v_hash and d.status='COMPLETED'
   and d.result_json #>> '{run_summary,mode}'='RCT_FIRST_V1'
   and d.result_json #> '{run_summary,resume_eligible}'='true'::jsonb
   and d.completed_at <= clock_timestamp()-interval '10 minutes'
   and not exists(select 1 from public.discovery_jobs j where j.client_token_hash=v_hash
       and j.id<>d.id and j.specialty=d.specialty and j.question_type=d.question_type and j.status in ('QUEUED','RUNNING'));
  get diagnostics v_updated = row_count;
  return v_updated=1;
end;
$$;
revoke all on function public.scimed_resume_rct_job(uuid) from public,anon,authenticated;
grant execute on function public.scimed_resume_rct_job(uuid) to anon,authenticated;
notify pgrst, 'reload schema';
