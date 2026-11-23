-- SciMed Review Scout Cloud queue.
-- Public browser clients use a locally generated device token carried in
-- x-scimed-client-token. The background worker uses a separate secret token
-- carried in x-scimed-worker-token. The Supabase service-role key is not used.

create extension if not exists pgcrypto;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table if not exists private.scimed_worker_config (
  singleton boolean primary key default true check (singleton),
  token_hash text not null,
  updated_at timestamptz not null default now()
);

revoke all on table private.scimed_worker_config from public, anon, authenticated;

grant usage on schema private to anon, authenticated;

create or replace function private.scimed_client_hash()
returns text
language sql
stable
security invoker
set search_path = public, private, extensions
as $$
  select case
    when coalesce(current_setting('request.headers', true), '') = '' then null
    else encode(
      extensions.digest(
        coalesce((current_setting('request.headers', true)::jsonb ->> 'x-scimed-client-token'), ''),
        'sha256'
      ),
      'hex'
    )
  end
$$;

create or replace function private.scimed_is_worker()
returns boolean
language sql
stable
security definer
set search_path = public, private, extensions
as $$
  select exists (
    select 1
    from private.scimed_worker_config
    where token_hash = encode(
      extensions.digest(
        coalesce((current_setting('request.headers', true)::jsonb ->> 'x-scimed-worker-token'), ''),
        'sha256'
      ),
      'hex'
    )
  )
$$;

grant execute on function private.scimed_client_hash() to anon, authenticated;
grant execute on function private.scimed_is_worker() to anon, authenticated;

create table if not exists public.discovery_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid default auth.uid(),
  client_token_hash text not null default private.scimed_client_hash(),
  specialty text not null default 'ALL',
  question_type text not null default 'ALL',
  status text not null default 'QUEUED'
    check (status in ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')),
  stage text not null default 'QUEUED',
  progress integer not null default 0 check (progress between 0 and 100),
  message text not null default 'Waiting for background worker',
  candidate_count integer not null default 12 check (candidate_count between 4 and 50),
  final_options integer not null default 3 check (final_options between 2 and 10),
  min_verify integer not null default 3 check (min_verify between 1 and 20),
  max_verify integer not null default 10 check (max_verify between 2 and 30),
  limit_per_query integer not null default 20 check (limit_per_query between 5 and 100),
  revisit_days integer not null default 30 check (revisit_days between 0 and 180),
  dispatch_requested_at timestamptz,
  result_json jsonb not null default '{}'::jsonb,
  error_text text not null default '',
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.discovery_jobs
  alter column user_id drop not null;

alter table public.discovery_jobs
  add column if not exists dispatch_requested_at timestamptz;

alter table public.discovery_jobs
  add column if not exists revisit_days integer not null default 30;

alter table public.discovery_jobs
  drop constraint if exists discovery_jobs_revisit_days_check;
alter table public.discovery_jobs
  add constraint discovery_jobs_revisit_days_check
  check (revisit_days between 0 and 180);

alter table public.discovery_jobs
  add column if not exists client_token_hash text;

alter table public.discovery_jobs
  alter column client_token_hash set default private.scimed_client_hash();

update public.discovery_jobs
set client_token_hash = encode(extensions.digest(id::text, 'sha256'), 'hex')
where client_token_hash is null;

alter table public.discovery_jobs
  alter column client_token_hash set not null;

alter table public.discovery_jobs drop constraint if exists discovery_jobs_status_check;
alter table public.discovery_jobs
  add constraint discovery_jobs_status_check
  check (status in ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED'));

create index if not exists discovery_jobs_client_created_idx
  on public.discovery_jobs(client_token_hash, created_at desc);

create index if not exists discovery_jobs_worker_queue_idx
  on public.discovery_jobs(status, created_at asc);

alter table public.discovery_jobs enable row level security;

drop policy if exists "users_insert_own_discovery_jobs" on public.discovery_jobs;
drop policy if exists "users_read_own_discovery_jobs" on public.discovery_jobs;
drop policy if exists "clients_insert_own_discovery_jobs" on public.discovery_jobs;
drop policy if exists "clients_read_own_discovery_jobs" on public.discovery_jobs;
drop policy if exists "worker_updates_discovery_jobs" on public.discovery_jobs;

create policy "clients_insert_own_discovery_jobs"
  on public.discovery_jobs
  for insert
  to anon, authenticated
  with check (client_token_hash = private.scimed_client_hash());

create policy "clients_read_own_discovery_jobs"
  on public.discovery_jobs
  for select
  to anon, authenticated
  using (
    client_token_hash = private.scimed_client_hash()
    or private.scimed_is_worker()
  );

create policy "worker_updates_discovery_jobs"
  on public.discovery_jobs
  for update
  to anon, authenticated
  using (private.scimed_is_worker())
  with check (private.scimed_is_worker());

-- Configure the worker token separately. Store only SHA-256(token) here:
-- insert into private.scimed_worker_config(singleton, token_hash)
-- values (true, '<sha256>') on conflict (singleton) do update
-- set token_hash = excluded.token_hash, updated_at = now();


-- Safe device-scoped cancellation. Avoid an anonymous SECURITY DEFINER RPC.
-- The limited UPDATE policy allows only an owned active row; the trigger
-- restores all fields except the status change, so clients cannot forge results.
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
  end if;

  raise exception 'Unauthorized discovery job status transition';
end;
$$;

drop trigger if exists scimed_cancel_guard on public.discovery_jobs;
create trigger scimed_cancel_guard
before update on public.discovery_jobs
for each row execute function private.scimed_cancel_guard();

drop policy if exists "clients_cancel_own_discovery_jobs" on public.discovery_jobs;
create policy "clients_cancel_own_discovery_jobs"
on public.discovery_jobs for update to anon, authenticated
using (
  client_token_hash = private.scimed_client_hash()
  and status in ('QUEUED','RUNNING')
)
with check (
  client_token_hash = private.scimed_client_hash()
  and status = 'CANCELLED'
);

create or replace function public.scimed_cancel_job(p_job_id uuid)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_client_hash text;
  v_updated integer;
begin
  v_client_hash := private.scimed_client_hash();
  if v_client_hash is null or length(v_client_hash) <> 64 then
    return false;
  end if;
  update public.discovery_jobs set status='CANCELLED'
  where id=p_job_id
    and client_token_hash=v_client_hash
    and status in ('QUEUED','RUNNING');
  get diagnostics v_updated = row_count;
  return v_updated=1;
end;
$$;

revoke all on function public.scimed_cancel_job(uuid) from public;
grant execute on function public.scimed_cancel_job(uuid) to anon, authenticated;

-- Strict device-owned retry for FAILED jobs only. No global update privileges.
drop policy if exists "clients_retry_own_failed_discovery_jobs" on public.discovery_jobs;
create policy "clients_retry_own_failed_discovery_jobs"
on public.discovery_jobs for update to anon, authenticated
using (
  client_token_hash=private.scimed_client_hash() and status='FAILED'
)
with check (
  client_token_hash=private.scimed_client_hash() and status='QUEUED'
);

create or replace function public.scimed_retry_job(p_job_id uuid)
returns boolean language plpgsql security invoker set search_path=''
as $$
declare
  v_client_hash text;
  v_updated integer;
begin
  v_client_hash := private.scimed_client_hash();
  if v_client_hash is null or length(v_client_hash) <> 64 then return false; end if;
  update public.discovery_jobs set status='QUEUED'
  where id=p_job_id
    and client_token_hash=v_client_hash
    and status='FAILED';
  get diagnostics v_updated = row_count;
  return v_updated=1;
end;
$$;

revoke all on function public.scimed_retry_job(uuid) from public;
grant execute on function public.scimed_retry_job(uuid) to anon, authenticated;
