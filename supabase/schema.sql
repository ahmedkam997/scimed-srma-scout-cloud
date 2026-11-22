-- SciMed Review Scout Cloud
-- Run this file once in Supabase SQL Editor.
-- Then enable Anonymous Sign-Ins in Authentication settings.

create extension if not exists pgcrypto;

create table if not exists public.discovery_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid(),
  specialty text not null default 'ALL',
  question_type text not null default 'ALL',
  status text not null default 'QUEUED'
    check (status in ('QUEUED','RUNNING','COMPLETED','FAILED')),
  stage text not null default 'QUEUED',
  progress integer not null default 0 check (progress between 0 and 100),
  message text not null default 'Waiting for background worker',
  candidate_count integer not null default 12 check (candidate_count between 4 and 50),
  final_options integer not null default 3 check (final_options between 2 and 10),
  min_verify integer not null default 3 check (min_verify between 1 and 20),
  max_verify integer not null default 10 check (max_verify between 2 and 30),
  limit_per_query integer not null default 20 check (limit_per_query between 5 and 100),
  result_json jsonb not null default '{}'::jsonb,
  error_text text not null default '',
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists discovery_jobs_user_created_idx
  on public.discovery_jobs(user_id, created_at desc);

create index if not exists discovery_jobs_worker_queue_idx
  on public.discovery_jobs(status, created_at asc);

alter table public.discovery_jobs enable row level security;

drop policy if exists "users_insert_own_discovery_jobs" on public.discovery_jobs;
create policy "users_insert_own_discovery_jobs"
  on public.discovery_jobs
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "users_read_own_discovery_jobs" on public.discovery_jobs;
create policy "users_read_own_discovery_jobs"
  on public.discovery_jobs
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

-- Browser clients deliberately receive no UPDATE or DELETE policy.
-- The GitHub Actions worker uses the service-role key and updates job state server-side only.
