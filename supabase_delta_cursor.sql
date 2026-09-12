-- ===========================================================================
-- Digital Service Pakistan - delta sync cursor fix
-- ===========================================================================
-- Run this ONCE in the Supabase SQL editor, after supabase_schema.sql,
-- supabase_delta_sync.sql and supabase_inventory_slots.sql. Safe to re-run.
--
-- THE BUG THIS FIXES
-- Delta sync asked the server for "rows changed since <watermark>", where
-- the watermark was the row's own updated_at - a business timestamp set on
-- the device. When a PC is offline for hours and then pushes its backlog,
-- those rows arrive at the cloud with OLD updated_at values. If the puller
-- had already moved its watermark past them, they were filtered out and
-- never seen again. That is how attendance events went missing: a check-in
-- from 12:21 reached the cloud after the watermark had advanced to 16:21,
-- so it was skipped permanently.
--
-- THE FIX
-- Every synced table gains cloud_updated_at, stamped by the DATABASE at the
-- moment the row is written. The readers filter and order on that instead.
-- A late-arriving old row still looks new to the puller, so it comes
-- through. A trigger does the stamping, so every write path is covered -
-- now and for anything added later.
-- ===========================================================================

-- --- 1. the column, on every table that feeds a delta stream --------------
-- Added nullable, backfilled from updated_at, then made NOT NULL. Adding it
-- straight away as "not null default now()" would stamp every historical row
-- with the migration time, and an app still on the old build would then
-- re-download the entire table every sync cycle until its cursor caught up.
-- Backfilling keeps old builds behaving exactly as they do today.
-- dsp_employee_users
alter table public.dsp_employee_users
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_employee_users
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_employee_users
  alter column cloud_updated_at set default now();
alter table public.dsp_employee_users
  alter column cloud_updated_at set not null;
-- dsp_inventory_items
alter table public.dsp_inventory_items
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_inventory_items
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_inventory_items
  alter column cloud_updated_at set default now();
alter table public.dsp_inventory_items
  alter column cloud_updated_at set not null;
-- dsp_inventory_slot_uses
alter table public.dsp_inventory_slot_uses
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_inventory_slot_uses
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_inventory_slot_uses
  alter column cloud_updated_at set default now();
alter table public.dsp_inventory_slot_uses
  alter column cloud_updated_at set not null;
-- dsp_app_settings
alter table public.dsp_app_settings
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_app_settings
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_app_settings
  alter column cloud_updated_at set default now();
alter table public.dsp_app_settings
  alter column cloud_updated_at set not null;
-- dsp_attendance_days
alter table public.dsp_attendance_days
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_attendance_days
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_attendance_days
  alter column cloud_updated_at set default now();
alter table public.dsp_attendance_days
  alter column cloud_updated_at set not null;
-- dsp_attendance_shifts
alter table public.dsp_attendance_shifts
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_attendance_shifts
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_attendance_shifts
  alter column cloud_updated_at set default now();
alter table public.dsp_attendance_shifts
  alter column cloud_updated_at set not null;
-- dsp_attendance_day_events
alter table public.dsp_attendance_day_events
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_attendance_day_events
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_attendance_day_events
  alter column cloud_updated_at set default now();
alter table public.dsp_attendance_day_events
  alter column cloud_updated_at set not null;
-- dsp_attendance_events
alter table public.dsp_attendance_events
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_attendance_events
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_attendance_events
  alter column cloud_updated_at set default now();
alter table public.dsp_attendance_events
  alter column cloud_updated_at set not null;
-- dsp_sales_entries
alter table public.dsp_sales_entries
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_sales_entries
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_sales_entries
  alter column cloud_updated_at set default now();
alter table public.dsp_sales_entries
  alter column cloud_updated_at set not null;

-- --- 2. index it: this is what every delta read now filters on ----------
create index if not exists dsp_employee_users_cloud_updated_idx
  on public.dsp_employee_users (cloud_updated_at desc);
create index if not exists dsp_inventory_items_cloud_updated_idx
  on public.dsp_inventory_items (cloud_updated_at desc);
create index if not exists dsp_inventory_slot_uses_cloud_updated_idx
  on public.dsp_inventory_slot_uses (cloud_updated_at desc);
create index if not exists dsp_app_settings_cloud_updated_idx
  on public.dsp_app_settings (cloud_updated_at desc);
create index if not exists dsp_attendance_days_cloud_updated_idx
  on public.dsp_attendance_days (cloud_updated_at desc);
create index if not exists dsp_attendance_shifts_cloud_updated_idx
  on public.dsp_attendance_shifts (cloud_updated_at desc);
create index if not exists dsp_attendance_day_events_cloud_updated_idx
  on public.dsp_attendance_day_events (cloud_updated_at desc);
create index if not exists dsp_attendance_events_cloud_updated_idx
  on public.dsp_attendance_events (cloud_updated_at desc);
create index if not exists dsp_sales_entries_cloud_updated_idx
  on public.dsp_sales_entries (cloud_updated_at desc);

-- --- 3. stamp it automatically on every insert and update ----------------
-- Created AFTER the backfill above on purpose: the trigger fires on UPDATE,
-- so backfilling with it in place would stamp every row with now() and undo
-- the whole point. On a re-run the backfill matches no rows, so the order
-- stays safe.
-- A trigger rather than editing each upsert function: it cannot be forgotten
-- by a future write path, and it keeps the upserts untouched.
create or replace function public.dsp_stamp_cloud_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.cloud_updated_at := now();
  return new;
end;
$$;
drop trigger if exists dsp_employee_users_cloud_stamp on public.dsp_employee_users;
create trigger dsp_employee_users_cloud_stamp
  before insert or update on public.dsp_employee_users
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_inventory_items_cloud_stamp on public.dsp_inventory_items;
create trigger dsp_inventory_items_cloud_stamp
  before insert or update on public.dsp_inventory_items
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_inventory_slot_uses_cloud_stamp on public.dsp_inventory_slot_uses;
create trigger dsp_inventory_slot_uses_cloud_stamp
  before insert or update on public.dsp_inventory_slot_uses
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_app_settings_cloud_stamp on public.dsp_app_settings;
create trigger dsp_app_settings_cloud_stamp
  before insert or update on public.dsp_app_settings
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_attendance_days_cloud_stamp on public.dsp_attendance_days;
create trigger dsp_attendance_days_cloud_stamp
  before insert or update on public.dsp_attendance_days
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_attendance_shifts_cloud_stamp on public.dsp_attendance_shifts;
create trigger dsp_attendance_shifts_cloud_stamp
  before insert or update on public.dsp_attendance_shifts
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_attendance_day_events_cloud_stamp on public.dsp_attendance_day_events;
create trigger dsp_attendance_day_events_cloud_stamp
  before insert or update on public.dsp_attendance_day_events
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_attendance_events_cloud_stamp on public.dsp_attendance_events;
create trigger dsp_attendance_events_cloud_stamp
  before insert or update on public.dsp_attendance_events
  for each row execute function public.dsp_stamp_cloud_updated_at();
drop trigger if exists dsp_sales_entries_cloud_stamp on public.dsp_sales_entries;
create trigger dsp_sales_entries_cloud_stamp
  before insert or update on public.dsp_sales_entries
  for each row execute function public.dsp_stamp_cloud_updated_at();

-- --- 4. the readers now use the server clock ----------------------------
-- Each gains a cloud_updated_at column, filters on it, and orders by it so
-- the row limit truncates the least recently written rather than the
-- oldest by business date. Adding a column to the result means the old
-- function must be dropped first (Postgres 42P13).

drop function if exists public.dsp_list_app_settings_delta(text, text);
create or replace function public.dsp_list_app_settings_delta(sync_secret text, since text)
returns table (
  setting_key text,
  setting_value text,
  updated_at timestamptz,
  cloud_updated_at timestamptz
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
  select s.setting_key, s.setting_value, s.updated_at, s.cloud_updated_at
  from public.dsp_app_settings s
  where (cutoff is null or s.cloud_updated_at > cutoff);
end;
$$;

drop function if exists public.dsp_list_attendance_day_events_delta(text, text);
create or replace function public.dsp_list_attendance_day_events_delta(admin_secret text, since text)
returns table (
  cloud_id text,
  day_cloud_id text,
  employee_username text,
  day_date date,
  event_type text,
  event_label text,
  event_time timestamptz,
  details text,
  updated_at timestamptz,
  cloud_updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select e.cloud_id, e.day_cloud_id, e.employee_username, e.day_date, e.event_type, e.event_label,
         e.event_time, e.details, e.updated_at, e.cloud_updated_at
  from public.dsp_attendance_day_events e
  where e.day_date >= (now() - interval '35 days')::date
    and (cutoff is null or e.cloud_updated_at > cutoff)
  order by e.cloud_updated_at desc
  limit 5000;
end;
$$;

drop function if exists public.dsp_list_attendance_days_delta(text, text);
create or replace function public.dsp_list_attendance_days_delta(admin_secret text, since text)
returns table (
  cloud_id text,
  employee_username text,
  day_date date,
  status text,
  started_at timestamptz,
  ended_at timestamptz,
  updated_at timestamptz,
  cloud_updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select d.cloud_id, d.employee_username, d.day_date, d.status, d.started_at, d.ended_at, d.updated_at, d.cloud_updated_at
  from public.dsp_attendance_days d
  where d.day_date >= (now() - interval '35 days')::date
    and (cutoff is null or d.cloud_updated_at > cutoff)
  order by d.cloud_updated_at desc
  limit 3000;
end;
$$;

drop function if exists public.dsp_list_attendance_events_delta(text, text);
create or replace function public.dsp_list_attendance_events_delta(admin_secret text, since text)
returns table (
  cloud_id text,
  shift_cloud_id text,
  employee_username text,
  shift_date date,
  shift_number integer,
  event_type text,
  event_label text,
  event_time timestamptz,
  details text,
  updated_at timestamptz,
  cloud_updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select e.cloud_id, e.shift_cloud_id, e.employee_username, e.shift_date, e.shift_number,
         e.event_type, e.event_label, e.event_time, e.details, e.updated_at, e.cloud_updated_at
  from public.dsp_attendance_events e
  where e.shift_date >= (now() - interval '35 days')::date
    and (cutoff is null or e.cloud_updated_at > cutoff)
  order by e.cloud_updated_at desc
  limit 5000;
end;
$$;

drop function if exists public.dsp_list_attendance_shifts_delta(text, text);
create or replace function public.dsp_list_attendance_shifts_delta(admin_secret text, since text)
returns table (
  cloud_id text,
  employee_username text,
  shift_date date,
  shift_number integer,
  status text,
  started_at timestamptz,
  ended_at timestamptz,
  break_count integer,
  total_break_seconds integer,
  current_break_started_at timestamptz,
  updated_at timestamptz,
  cloud_updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select s.cloud_id, s.employee_username, s.shift_date, s.shift_number, s.status, s.started_at, s.ended_at,
         s.break_count, s.total_break_seconds, s.current_break_started_at, s.updated_at, s.cloud_updated_at
  from public.dsp_attendance_shifts s
  where s.shift_date >= (now() - interval '35 days')::date
    and (cutoff is null or s.cloud_updated_at > cutoff)
  order by s.cloud_updated_at desc
  limit 3000;
end;
$$;

drop function if exists public.dsp_list_employee_users_delta(text, text);
create or replace function public.dsp_list_employee_users_delta(sync_secret text, since text)
returns table (
  username_key text,
  username text,
  display_name text,
  role text,
  is_active boolean,
  is_deleted boolean,
  password_hash text,
  created_at timestamptz,
  updated_at timestamptz,
  deleted_at timestamptz,
  cloud_updated_at timestamptz
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
  select u.username_key, u.username, u.display_name, u.role, u.is_active, u.is_deleted,
         u.password_hash, u.created_at, u.updated_at, u.deleted_at, u.cloud_updated_at
  from public.dsp_employee_users u
  where (cutoff is null or u.cloud_updated_at > cutoff)
  order by u.cloud_updated_at desc;
end;
$$;

drop function if exists public.dsp_list_inventory_items_delta(text, text);
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
  is_active boolean,
  cloud_updated_at timestamptz
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
         i.created_by, i.created_at, i.updated_at, i.is_active, i.cloud_updated_at
  from public.dsp_inventory_items i
  where (cutoff is null or i.cloud_updated_at > cutoff)
  order by i.cloud_updated_at desc;
end;
$$;

drop function if exists public.dsp_list_inventory_slot_uses_delta(text, text);
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
  is_active boolean,
  cloud_updated_at timestamptz
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
         u.used_by, u.updated_by, u.created_at, u.updated_at, u.is_active, u.cloud_updated_at
  from public.dsp_inventory_slot_uses u
  where (cutoff is null or u.cloud_updated_at > cutoff)
  order by u.cloud_updated_at desc;
end;
$$;

drop function if exists public.dsp_list_sales_entries_delta(text, text);
create or replace function public.dsp_list_sales_entries_delta(admin_secret text, since text)
returns table (
  cloud_id text,
  employee_username text,
  entry_date date,
  entry_time text,
  customer text,
  item text,
  order_id text,
  buying_amount text,
  selling_amount text,
  profit text,
  status text,
  notes text,
  excel_row integer,
  excel_synced_at text,
  excel_sync_error text,
  created_at timestamptz,
  updated_at timestamptz,
  cloud_updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare cutoff timestamptz;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select s.cloud_id, s.employee_username, s.entry_date, s.entry_time, s.customer, s.item, s.order_id,
         s.buying_amount, s.selling_amount, s.profit, s.status, s.notes,
         s.excel_row, s.excel_synced_at, s.excel_sync_error, s.created_at, s.updated_at, s.cloud_updated_at
  from public.dsp_sales_entries s
  where (cutoff is null or s.cloud_updated_at > cutoff)
  order by s.cloud_updated_at desc
  limit 5000;
end;
$$;

drop function if exists public.dsp_list_sales_entries_shared_delta(text, text);
create or replace function public.dsp_list_sales_entries_shared_delta(sync_secret text, since text)
returns table (
  cloud_id text,
  employee_username text,
  entry_date date,
  entry_time text,
  customer text,
  item text,
  order_id text,
  buying_amount text,
  selling_amount text,
  profit text,
  status text,
  notes text,
  excel_row integer,
  excel_synced_at text,
  excel_sync_error text,
  created_at timestamptz,
  updated_at timestamptz,
  cloud_updated_at timestamptz
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
  select s.cloud_id, s.employee_username, s.entry_date, s.entry_time, s.customer, s.item, s.order_id,
         s.buying_amount, s.selling_amount, s.profit, s.status, s.notes,
         s.excel_row, s.excel_synced_at, s.excel_sync_error, s.created_at, s.updated_at, s.cloud_updated_at
  from public.dsp_sales_entries s
  where (cutoff is null or s.cloud_updated_at > cutoff)
  order by s.cloud_updated_at desc
  limit 5000;
end;
$$;

-- --- 5. grants (dropping a function drops its grants) --------------------
grant execute on function public.dsp_list_app_settings_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_day_events_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_days_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_events_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_shifts_delta(text, text) to anon;
grant execute on function public.dsp_list_employee_users_delta(text, text) to anon;
grant execute on function public.dsp_list_inventory_items_delta(text, text) to anon;
grant execute on function public.dsp_list_inventory_slot_uses_delta(text, text) to anon;
grant execute on function public.dsp_list_sales_entries_delta(text, text) to anon;
grant execute on function public.dsp_list_sales_entries_shared_delta(text, text) to anon;

-- --- 6. the three table-select streams need the same stamp ---------------
-- announcements / templates / service catalog are pulled with a PostgREST
-- filter rather than an RPC, but the flaw is identical, so they get the
-- same server-side column, index and trigger.
-- dsp_announcements
alter table public.dsp_announcements
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_announcements
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_announcements
  alter column cloud_updated_at set default now();
alter table public.dsp_announcements
  alter column cloud_updated_at set not null;
create index if not exists dsp_announcements_cloud_updated_idx
  on public.dsp_announcements (cloud_updated_at desc);
drop trigger if exists dsp_announcements_cloud_stamp on public.dsp_announcements;
create trigger dsp_announcements_cloud_stamp
  before insert or update on public.dsp_announcements
  for each row execute function public.dsp_stamp_cloud_updated_at();
-- dsp_service_message_templates
alter table public.dsp_service_message_templates
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_service_message_templates
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_service_message_templates
  alter column cloud_updated_at set default now();
alter table public.dsp_service_message_templates
  alter column cloud_updated_at set not null;
create index if not exists dsp_service_message_templates_cloud_updated_idx
  on public.dsp_service_message_templates (cloud_updated_at desc);
drop trigger if exists dsp_service_message_templates_cloud_stamp on public.dsp_service_message_templates;
create trigger dsp_service_message_templates_cloud_stamp
  before insert or update on public.dsp_service_message_templates
  for each row execute function public.dsp_stamp_cloud_updated_at();
-- dsp_service_catalog
alter table public.dsp_service_catalog
  add column if not exists cloud_updated_at timestamptz;
update public.dsp_service_catalog
  set cloud_updated_at = coalesce(updated_at, now())
  where cloud_updated_at is null;
alter table public.dsp_service_catalog
  alter column cloud_updated_at set default now();
alter table public.dsp_service_catalog
  alter column cloud_updated_at set not null;
create index if not exists dsp_service_catalog_cloud_updated_idx
  on public.dsp_service_catalog (cloud_updated_at desc);
drop trigger if exists dsp_service_catalog_cloud_stamp on public.dsp_service_catalog;
create trigger dsp_service_catalog_cloud_stamp
  before insert or update on public.dsp_service_catalog
  for each row execute function public.dsp_stamp_cloud_updated_at();
