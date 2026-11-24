-- Request-only GitHub Actions dispatch for queued research source rechecks.
-- Browser bearer-token RLS, no alteration of study reports or scientific gates.
alter table public.scimed_source_rechecks
  add column if not exists dispatch_requested_at timestamptz;

-- Workers already have column-specific UPDATE grants via their restricted
-- RLS policy. Client UPDATE is allowed only for this timestamp and controlled
-- by an additional immutable-fields trigger.
grant update(dispatch_requested_at) on public.scimed_source_rechecks
to anon,authenticated;

create policy scimed_recheck_owner_dispatch
on public.scimed_source_rechecks
for update to anon,authenticated
using (
  status='QUEUED'
  and client_token_hash=private.scimed_client_hash()
  and char_length(coalesce(
    (current_setting('request.headers',true)::jsonb ->> 'x-scimed-client-token'),''
  ))>=32
)
with check (
  status='QUEUED'
  and client_token_hash=private.scimed_client_hash()
);

create or replace function private.scimed_recheck_dispatch_guard()
returns trigger
language plpgsql
security invoker
set search_path to ''
as $guard$
begin
  if private.scimed_is_worker() then
    return new;
  end if;
  if (to_jsonb(new)-'dispatch_requested_at') is distinct from
     (to_jsonb(old)-'dispatch_requested_at') then
    raise exception 'Browser dispatch may update only dispatch_requested_at'
      using errcode='42501';
  end if;
  if old.dispatch_requested_at is not null and
     old.dispatch_requested_at > clock_timestamp()-interval '120 seconds' then
    raise exception 'A source recheck dispatch was requested recently'
      using errcode='42501';
  end if;
  new.dispatch_requested_at:=clock_timestamp();
  return new;
end;
$guard$;

drop trigger if exists scimed_recheck_dispatch_guard on public.scimed_source_rechecks;
create trigger scimed_recheck_dispatch_guard
before update on public.scimed_source_rechecks
for each row execute function private.scimed_recheck_dispatch_guard();

create or replace function public.scimed_request_recheck_dispatch(p_recheck_id uuid)
returns boolean
language plpgsql
security invoker
set search_path to ''
as $function$
declare
  v_hash text;
  v_updated integer;
begin
  v_hash:=private.scimed_client_hash();
  if v_hash is null or length(v_hash) <> 64 then return false; end if;

  update public.scimed_source_rechecks
  set dispatch_requested_at=clock_timestamp()
  where id=p_recheck_id
    and client_token_hash=v_hash
    and status='QUEUED'
    and (dispatch_requested_at is null or
         dispatch_requested_at < clock_timestamp()-interval '120 seconds');
  get diagnostics v_updated=row_count;
  return v_updated=1;
end;
$function$;

revoke all on function public.scimed_request_recheck_dispatch(uuid) from public;
grant execute on function public.scimed_request_recheck_dispatch(uuid)
  to anon,authenticated;
comment on function public.scimed_request_recheck_dispatch(uuid) is
  'Reserve 1 workflow dispatch per browser-owned QUEUED source recheck per 120 seconds; never grants study or worker permissions.';
