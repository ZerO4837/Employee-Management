-- ===========================================================================
-- Digital Service Pakistan - Inventory upgrade (timed services + slot sharing)
-- ===========================================================================
-- Run this ONCE in the Supabase SQL editor, on top of supabase_schema.sql and
-- supabase_delta_sync.sql. It is safe to re-run: everything is either
-- "if not exists" or "create or replace", and no row is ever deleted.
--
-- What it adds:
--   1. Four columns on dsp_inventory_items so an account knows whether it is
--      a timed service (Proton VPN: purchase date + 30 days) or a shared
--      slot account (Canva / Spotify / Adobe: a number of slots).
--   2. dsp_inventory_slot_uses - one row per client sitting in one slot.
--      Employees write to this table (they are the ones seating clients), so
--      its upsert is gated by the EMPLOYEE sync secret, not the admin one.
--   3. The list / delta readers for both.
-- ===========================================================================

-- --- 1. inventory items gain a kind ---------------------------------------
alter table public.dsp_inventory_items
  add column if not exists item_kind text not null default 'timed';
alter table public.dsp_inventory_items
  add column if not exists purchase_date text not null default '';
alter table public.dsp_inventory_items
  add column if not exists valid_days integer not null default 30;
alter table public.dsp_inventory_items
  add column if not exists total_slots integer not null default 0;

-- --- 2. one row per client in one slot -------------------------------------
create table if not exists public.dsp_inventory_slot_uses (
  cloud_id text primary key,
  item_cloud_id text not null default '',
  client_email text not null default '',
  package text not null default '',
  notes text not null default '',
  used_by text not null default '',
  updated_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  is_active boolean not null default true
);

create index if not exists dsp_inventory_slot_uses_item_idx
on public.dsp_inventory_slot_uses (item_cloud_id, is_active, updated_at desc);

create index if not exists dsp_inventory_slot_uses_updated_idx
on public.dsp_inventory_slot_uses (updated_at desc);

alter table public.dsp_inventory_slot_uses enable row level security;
revoke all on table public.dsp_inventory_slot_uses from anon, authenticated;

-- --- 3. write path (employee-gated) ----------------------------------------
create or replace function public.dsp_upsert_inventory_slot_use(sync_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  insert into public.dsp_inventory_slot_uses (
    cloud_id, item_cloud_id, client_email, package, notes,
    used_by, updated_by, created_at, updated_at, is_active
  )
  values (
    row_data->>'cloud_id',
    coalesce(row_data->>'item_cloud_id', ''),
    coalesce(row_data->>'client_email', ''),
    coalesce(row_data->>'package', ''),
    coalesce(row_data->>'notes', ''),
    coalesce(row_data->>'used_by', ''),
    coalesce(row_data->>'updated_by', ''),
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'is_active', '')::boolean, true)
  )
  on conflict (cloud_id) do update set
    item_cloud_id = excluded.item_cloud_id,
    client_email = excluded.client_email,
    package = excluded.package,
    notes = excluded.notes,
    used_by = excluded.used_by,
    updated_by = excluded.updated_by,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    is_active = excluded.is_active;
end;
$$;

-- --- 4. read paths ----------------------------------------------------------
create or replace function public.dsp_list_inventory_slot_uses(sync_secret text)
returns table (
  cloud_id text,
  item_cloud_id text,
  client_email text,
  package text,
  notes text,
  used_by text,
  updated_by text,
  created_at timestamptz,
  updated_at timestamptz,
  is_active boolean
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  return query
  select u.cloud_id, u.item_cloud_id, u.client_email, u.package, u.notes,
         u.used_by, u.updated_by, u.created_at, u.updated_at, u.is_active
  from public.dsp_inventory_slot_uses u
  order by u.item_cloud_id asc, u.created_at asc;
end;
$$;

create or replace function public.dsp_list_inventory_slot_uses_delta(sync_secret text, since text)
returns table (
  cloud_id text,
  item_cloud_id text,
  client_email text,
  package text,
  notes text,
  used_by text,
  updated_by text,
  created_at timestamptz,
  updated_at timestamptz,
  is_active boolean
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select u.cloud_id, u.item_cloud_id, u.client_email, u.package, u.notes,
         u.used_by, u.updated_by, u.created_at, u.updated_at, u.is_active
  from public.dsp_inventory_slot_uses u
  where (cutoff is null or u.updated_at > cutoff)
  order by u.updated_at desc;
end;
$$;

-- --- 5. the inventory readers must carry the new columns --------------------
-- These two readers gain four columns, and Postgres will not let
-- "create or replace" change a function's return type:
--   ERROR 42P13: cannot change return type of existing function
-- So drop them first. Dropping also drops their grants, which is why the
-- grant block at the bottom of this file re-applies them.
-- The signatures stay the same, so an app still running the old version
-- keeps working - it simply ignores the extra columns.
drop function if exists public.dsp_list_inventory_items(text);
drop function if exists public.dsp_list_inventory_items_delta(text, text);

create or replace function public.dsp_upsert_inventory_item(admin_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  insert into public.dsp_inventory_items (
    cloud_id, service_name, account_email, account_password, comment,
    item_kind, purchase_date, valid_days, total_slots,
    created_by, created_at, updated_at, is_active
  )
  values (
    row_data->>'cloud_id',
    coalesce(row_data->>'service_name', ''),
    coalesce(row_data->>'account_email', ''),
    coalesce(row_data->>'account_password', ''),
    coalesce(row_data->>'comment', ''),
    coalesce(nullif(row_data->>'item_kind', ''), 'timed'),
    coalesce(row_data->>'purchase_date', ''),
    coalesce(nullif(row_data->>'valid_days', '')::integer, 30),
    coalesce(nullif(row_data->>'total_slots', '')::integer, 0),
    coalesce(row_data->>'created_by', ''),
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'is_active', '')::boolean, true)
  )
  on conflict (cloud_id) do update set
    service_name = excluded.service_name,
    account_email = excluded.account_email,
    account_password = excluded.account_password,
    comment = excluded.comment,
    item_kind = excluded.item_kind,
    purchase_date = excluded.purchase_date,
    valid_days = excluded.valid_days,
    total_slots = excluded.total_slots,
    created_by = excluded.created_by,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    is_active = excluded.is_active;
end;
$$;

create or replace function public.dsp_list_inventory_items(sync_secret text)
returns table (
  cloud_id text,
  service_name text,
  account_email text,
  account_password text,
  comment text,
  item_kind text,
  purchase_date text,
  valid_days integer,
  total_slots integer,
  created_by text,
  created_at timestamptz,
  updated_at timestamptz,
  is_active boolean
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  return query
  select i.cloud_id, i.service_name, i.account_email, i.account_password, i.comment,
         i.item_kind, i.purchase_date, i.valid_days, i.total_slots,
         i.created_by, i.created_at, i.updated_at, i.is_active
  from public.dsp_inventory_items i
  order by i.service_name asc, i.account_email asc, i.updated_at desc;
end;
$$;

create or replace function public.dsp_list_inventory_items_delta(sync_secret text, since text)
returns table (
  cloud_id text,
  service_name text,
  account_email text,
  account_password text,
  comment text,
  item_kind text,
  purchase_date text,
  valid_days integer,
  total_slots integer,
  created_by text,
  created_at timestamptz,
  updated_at timestamptz,
  is_active boolean
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select i.cloud_id, i.service_name, i.account_email, i.account_password, i.comment,
         i.item_kind, i.purchase_date, i.valid_days, i.total_slots,
         i.created_by, i.created_at, i.updated_at, i.is_active
  from public.dsp_inventory_items i
  where (cutoff is null or i.updated_at > cutoff)
  order by i.updated_at desc;
end;
$$;

-- --- 6. grants --------------------------------------------------------------
grant execute on function public.dsp_upsert_inventory_slot_use(text, jsonb) to anon;
grant execute on function public.dsp_list_inventory_slot_uses(text) to anon;
grant execute on function public.dsp_list_inventory_slot_uses_delta(text, text) to anon;
grant execute on function public.dsp_upsert_inventory_item(text, jsonb) to anon;
grant execute on function public.dsp_list_inventory_items(text) to anon;
grant execute on function public.dsp_list_inventory_items_delta(text, text) to anon;
