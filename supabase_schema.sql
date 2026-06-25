-- Digital Service Pakistan Employee App - Supabase cloud sync schema
-- Run this once in Supabase Dashboard > SQL Editor.
-- IMPORTANT: Change CHANGE_THIS_ADMIN_SECRET before running, then use the same value in the app Admin > Cloud Sync tab.
-- IMPORTANT: Change CHANGE_THIS_EMPLOYEE_SYNC_SECRET before running, then use that value on employee PCs so they can pull employee account updates.

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.dsp_cloud_settings (
  setting_key text primary key,
  setting_value text not null,
  updated_at timestamptz not null default now()
);

insert into public.dsp_cloud_settings (setting_key, setting_value, updated_at)
values ('admin_secret_hash', encode(extensions.digest('CHANGE_THIS_ADMIN_SECRET', 'sha256'), 'hex'), now())
on conflict (setting_key) do update
set setting_value = excluded.setting_value,
    updated_at = now();

insert into public.dsp_cloud_settings (setting_key, setting_value, updated_at)
values ('employee_sync_secret_hash', encode(extensions.digest('CHANGE_THIS_EMPLOYEE_SYNC_SECRET', 'sha256'), 'hex'), now())
on conflict (setting_key) do update
set setting_value = excluded.setting_value,
    updated_at = now();

create table if not exists public.dsp_announcements (
  cloud_id text primary key,
  category text not null default '',
  title text not null default '',
  message text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  is_active boolean not null default true
);

create index if not exists dsp_announcements_active_idx
on public.dsp_announcements (is_active, created_at desc);

create table if not exists public.dsp_service_message_templates (
  cloud_id text primary key,
  service_name text not null default '',
  title text not null default '',
  message text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  is_active boolean not null default true
);

create index if not exists dsp_service_message_templates_active_idx
on public.dsp_service_message_templates (is_active, service_name, updated_at desc);

create table if not exists public.dsp_service_catalog (
  cloud_id text primary key,
  service_name text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  is_active boolean not null default true
);

create index if not exists dsp_service_catalog_active_idx
on public.dsp_service_catalog (is_active, service_name, updated_at desc);

create table if not exists public.dsp_employee_users (
  username_key text primary key,
  username text not null default '',
  display_name text not null default '',
  role text not null default 'employee',
  is_active boolean not null default true,
  is_deleted boolean not null default false,
  password_hash text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists dsp_employee_users_updated_idx
on public.dsp_employee_users (updated_at desc);

create table if not exists public.dsp_inventory_items (
  cloud_id text primary key,
  service_name text not null default '',
  account_email text not null default '',
  account_password text not null default '',
  comment text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  is_active boolean not null default true
);

create index if not exists dsp_inventory_items_active_idx
on public.dsp_inventory_items (is_active, service_name, account_email, updated_at desc);

create table if not exists public.dsp_attendance_days (
  cloud_id text primary key,
  employee_username text not null default '',
  day_date date not null,
  status text not null default 'active',
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists dsp_attendance_days_lookup_idx
on public.dsp_attendance_days (employee_username, day_date desc, status, updated_at desc);

create table if not exists public.dsp_attendance_shifts (
  cloud_id text primary key,
  employee_username text not null default '',
  shift_date date not null,
  shift_number integer not null default 1,
  status text not null default 'active',
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  break_count integer not null default 0,
  total_break_seconds integer not null default 0,
  current_break_started_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists dsp_attendance_shifts_lookup_idx
on public.dsp_attendance_shifts (employee_username, shift_date desc, shift_number, status, updated_at desc);

create table if not exists public.dsp_attendance_day_events (
  cloud_id text primary key,
  day_cloud_id text not null default '',
  employee_username text not null default '',
  day_date date not null,
  event_type text not null default '',
  event_label text not null default '',
  event_time timestamptz not null default now(),
  details text not null default '',
  updated_at timestamptz not null default now()
);

create index if not exists dsp_attendance_day_events_lookup_idx
on public.dsp_attendance_day_events (employee_username, day_date desc, event_time desc);

create table if not exists public.dsp_attendance_events (
  cloud_id text primary key,
  shift_cloud_id text not null default '',
  employee_username text not null default '',
  shift_date date not null,
  shift_number integer not null default 1,
  event_type text not null default '',
  event_label text not null default '',
  event_time timestamptz not null default now(),
  details text not null default '',
  updated_at timestamptz not null default now()
);

create index if not exists dsp_attendance_events_lookup_idx
on public.dsp_attendance_events (employee_username, shift_date desc, shift_number, event_time desc);

alter table public.dsp_cloud_settings enable row level security;
alter table public.dsp_announcements enable row level security;
alter table public.dsp_service_message_templates enable row level security;
alter table public.dsp_service_catalog enable row level security;
alter table public.dsp_employee_users enable row level security;
alter table public.dsp_inventory_items enable row level security;
alter table public.dsp_attendance_days enable row level security;
alter table public.dsp_attendance_shifts enable row level security;
alter table public.dsp_attendance_day_events enable row level security;
alter table public.dsp_attendance_events enable row level security;

revoke all on table public.dsp_cloud_settings from anon, authenticated;
revoke insert, update, delete on table public.dsp_announcements from anon, authenticated;
revoke insert, update, delete on table public.dsp_service_message_templates from anon, authenticated;
revoke insert, update, delete on table public.dsp_service_catalog from anon, authenticated;
revoke all on table public.dsp_employee_users from anon, authenticated;
revoke all on table public.dsp_inventory_items from anon, authenticated;
revoke all on table public.dsp_attendance_days from anon, authenticated;
revoke all on table public.dsp_attendance_shifts from anon, authenticated;
revoke all on table public.dsp_attendance_day_events from anon, authenticated;
revoke all on table public.dsp_attendance_events from anon, authenticated;
grant select on table public.dsp_announcements to anon;
grant select on table public.dsp_service_message_templates to anon;
grant select on table public.dsp_service_catalog to anon;

drop policy if exists "DSP employees can read announcements" on public.dsp_announcements;
create policy "DSP employees can read announcements"
on public.dsp_announcements
for select
to anon
using (true);

drop policy if exists "DSP employees can read service message templates" on public.dsp_service_message_templates;
create policy "DSP employees can read service message templates"
on public.dsp_service_message_templates
for select
to anon
using (true);

drop policy if exists "DSP employees can read service catalog" on public.dsp_service_catalog;
create policy "DSP employees can read service catalog"
on public.dsp_service_catalog
for select
to anon
using (true);

create or replace function public.dsp_admin_secret_valid(admin_secret text)
returns boolean
language sql
security definer
set search_path = public
as $$
  select encode(extensions.digest(coalesce(admin_secret, ''), 'sha256'), 'hex') = coalesce(
    (select setting_value from public.dsp_cloud_settings where setting_key = 'admin_secret_hash'),
    ''
  );
$$;

create or replace function public.dsp_employee_sync_secret_valid(sync_secret text)
returns boolean
language sql
security definer
set search_path = public
as $$
  select public.dsp_admin_secret_valid(sync_secret) or encode(extensions.digest(coalesce(sync_secret, ''), 'sha256'), 'hex') = coalesce(
    (select setting_value from public.dsp_cloud_settings where setting_key = 'employee_sync_secret_hash'),
    ''
  );
$$;

create or replace function public.dsp_upsert_employee_user(admin_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  key_value := lower(trim(coalesce(row_data->>'username_key', row_data->>'username', '')));
  if key_value = '' then
    raise exception 'Employee username is required' using errcode = '22023';
  end if;

  insert into public.dsp_employee_users (
    username_key, username, display_name, role, is_active, is_deleted, password_hash, created_at, updated_at, deleted_at
  )
  values (
    key_value,
    coalesce(row_data->>'username', key_value),
    coalesce(row_data->>'display_name', coalesce(row_data->>'username', key_value)),
    'employee',
    coalesce(nullif(row_data->>'is_active', '')::boolean, true),
    coalesce(nullif(row_data->>'is_deleted', '')::boolean, false),
    case when coalesce(nullif(row_data->>'is_deleted', '')::boolean, false) then '' else coalesce(row_data->>'password_hash', '') end,
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now()),
    case when nullif(row_data->>'deleted_at', '') is null then null else (row_data->>'deleted_at')::timestamptz end
  )
  on conflict (username_key) do update set
    username = excluded.username,
    display_name = excluded.display_name,
    role = 'employee',
    is_active = excluded.is_active,
    is_deleted = excluded.is_deleted,
    password_hash = excluded.password_hash,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    deleted_at = excluded.deleted_at;
end;
$$;

create or replace function public.dsp_list_employee_users(sync_secret text)
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
  deleted_at timestamptz
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
  select
    u.username_key,
    u.username,
    u.display_name,
    u.role,
    u.is_active,
    u.is_deleted,
    u.password_hash,
    u.created_at,
    u.updated_at,
    u.deleted_at
  from public.dsp_employee_users u
  order by u.updated_at desc, u.username_key asc;
end;
$$;

create or replace function public.dsp_upsert_service_catalog_item(admin_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  insert into public.dsp_service_catalog (
    cloud_id, service_name, created_by, created_at, updated_at, is_active
  )
  values (
    row_data->>'cloud_id',
    coalesce(row_data->>'service_name', ''),
    coalesce(row_data->>'created_by', ''),
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'is_active', '')::boolean, true)
  )
  on conflict (cloud_id) do update set
    service_name = excluded.service_name,
    created_by = excluded.created_by,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    is_active = excluded.is_active;
end;
$$;

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
    cloud_id, service_name, account_email, account_password, comment, created_by, created_at, updated_at, is_active
  )
  values (
    row_data->>'cloud_id',
    coalesce(row_data->>'service_name', ''),
    coalesce(row_data->>'account_email', ''),
    coalesce(row_data->>'account_password', ''),
    coalesce(row_data->>'comment', ''),
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
  select
    i.cloud_id,
    i.service_name,
    i.account_email,
    i.account_password,
    i.comment,
    i.created_by,
    i.created_at,
    i.updated_at,
    i.is_active
  from public.dsp_inventory_items i
  order by i.service_name asc, i.account_email asc, i.updated_at desc;
end;
$$;

create or replace function public.dsp_upsert_announcement(admin_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  insert into public.dsp_announcements (
    cloud_id, category, title, message, created_by, created_at, updated_at, is_active
  )
  values (
    row_data->>'cloud_id',
    coalesce(row_data->>'category', ''),
    coalesce(row_data->>'title', ''),
    coalesce(row_data->>'message', ''),
    coalesce(row_data->>'created_by', ''),
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'is_active', '')::boolean, true)
  )
  on conflict (cloud_id) do update set
    category = excluded.category,
    title = excluded.title,
    message = excluded.message,
    created_by = excluded.created_by,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    is_active = excluded.is_active;
end;
$$;

create or replace function public.dsp_upsert_service_message_template(admin_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  insert into public.dsp_service_message_templates (
    cloud_id, service_name, title, message, created_by, created_at, updated_at, is_active
  )
  values (
    row_data->>'cloud_id',
    coalesce(row_data->>'service_name', ''),
    coalesce(row_data->>'title', coalesce(row_data->>'service_name', '')),
    coalesce(row_data->>'message', ''),
    coalesce(row_data->>'created_by', ''),
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'is_active', '')::boolean, true)
  )
  on conflict (cloud_id) do update set
    service_name = excluded.service_name,
    title = excluded.title,
    message = excluded.message,
    created_by = excluded.created_by,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    is_active = excluded.is_active;
end;
$$;

create or replace function public.dsp_upsert_attendance_day(sync_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  key_value := trim(coalesce(row_data->>'cloud_id', ''));
  if key_value = '' then
    raise exception 'Attendance day cloud_id is required' using errcode = '22023';
  end if;

  insert into public.dsp_attendance_days (
    cloud_id, employee_username, day_date, status, started_at, ended_at, updated_at
  )
  values (
    key_value,
    coalesce(row_data->>'employee_username', ''),
    coalesce(nullif(row_data->>'day_date', '')::date, now()::date),
    coalesce(row_data->>'status', 'active'),
    coalesce(nullif(row_data->>'started_at', '')::timestamptz, now()),
    nullif(row_data->>'ended_at', '')::timestamptz,
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now())
  )
  on conflict (cloud_id) do update set
    employee_username = excluded.employee_username,
    day_date = excluded.day_date,
    status = excluded.status,
    started_at = excluded.started_at,
    ended_at = excluded.ended_at,
    updated_at = excluded.updated_at;
end;
$$;

create or replace function public.dsp_upsert_attendance_shift(sync_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  key_value := trim(coalesce(row_data->>'cloud_id', ''));
  if key_value = '' then
    raise exception 'Attendance shift cloud_id is required' using errcode = '22023';
  end if;

  insert into public.dsp_attendance_shifts (
    cloud_id, employee_username, shift_date, shift_number, status, started_at, ended_at,
    break_count, total_break_seconds, current_break_started_at, updated_at
  )
  values (
    key_value,
    coalesce(row_data->>'employee_username', ''),
    coalesce(nullif(row_data->>'shift_date', '')::date, now()::date),
    coalesce(nullif(row_data->>'shift_number', '')::integer, 1),
    coalesce(row_data->>'status', 'active'),
    coalesce(nullif(row_data->>'started_at', '')::timestamptz, now()),
    nullif(row_data->>'ended_at', '')::timestamptz,
    coalesce(nullif(row_data->>'break_count', '')::integer, 0),
    coalesce(nullif(row_data->>'total_break_seconds', '')::integer, 0),
    nullif(row_data->>'current_break_started_at', '')::timestamptz,
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now())
  )
  on conflict (cloud_id) do update set
    employee_username = excluded.employee_username,
    shift_date = excluded.shift_date,
    shift_number = excluded.shift_number,
    status = excluded.status,
    started_at = excluded.started_at,
    ended_at = excluded.ended_at,
    break_count = excluded.break_count,
    total_break_seconds = excluded.total_break_seconds,
    current_break_started_at = excluded.current_break_started_at,
    updated_at = excluded.updated_at;
end;
$$;

create or replace function public.dsp_upsert_attendance_day_event(sync_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  key_value := trim(coalesce(row_data->>'cloud_id', ''));
  if key_value = '' then
    raise exception 'Attendance day event cloud_id is required' using errcode = '22023';
  end if;

  insert into public.dsp_attendance_day_events (
    cloud_id, day_cloud_id, employee_username, day_date, event_type, event_label, event_time, details, updated_at
  )
  values (
    key_value,
    coalesce(row_data->>'day_cloud_id', ''),
    coalesce(row_data->>'employee_username', ''),
    coalesce(nullif(row_data->>'day_date', '')::date, now()::date),
    coalesce(row_data->>'event_type', ''),
    coalesce(row_data->>'event_label', ''),
    coalesce(nullif(row_data->>'event_time', '')::timestamptz, now()),
    coalesce(row_data->>'details', ''),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now())
  )
  on conflict (cloud_id) do update set
    day_cloud_id = excluded.day_cloud_id,
    employee_username = excluded.employee_username,
    day_date = excluded.day_date,
    event_type = excluded.event_type,
    event_label = excluded.event_label,
    event_time = excluded.event_time,
    details = excluded.details,
    updated_at = excluded.updated_at;
end;
$$;

create or replace function public.dsp_upsert_attendance_event(sync_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  key_value := trim(coalesce(row_data->>'cloud_id', ''));
  if key_value = '' then
    raise exception 'Attendance event cloud_id is required' using errcode = '22023';
  end if;

  insert into public.dsp_attendance_events (
    cloud_id, shift_cloud_id, employee_username, shift_date, shift_number, event_type, event_label, event_time, details, updated_at
  )
  values (
    key_value,
    coalesce(row_data->>'shift_cloud_id', ''),
    coalesce(row_data->>'employee_username', ''),
    coalesce(nullif(row_data->>'shift_date', '')::date, now()::date),
    coalesce(nullif(row_data->>'shift_number', '')::integer, 1),
    coalesce(row_data->>'event_type', ''),
    coalesce(row_data->>'event_label', ''),
    coalesce(nullif(row_data->>'event_time', '')::timestamptz, now()),
    coalesce(row_data->>'details', ''),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now())
  )
  on conflict (cloud_id) do update set
    shift_cloud_id = excluded.shift_cloud_id,
    employee_username = excluded.employee_username,
    shift_date = excluded.shift_date,
    shift_number = excluded.shift_number,
    event_type = excluded.event_type,
    event_label = excluded.event_label,
    event_time = excluded.event_time,
    details = excluded.details,
    updated_at = excluded.updated_at;
end;
$$;

create or replace function public.dsp_list_attendance_days(admin_secret text)
returns table (
  cloud_id text,
  employee_username text,
  day_date date,
  status text,
  started_at timestamptz,
  ended_at timestamptz,
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  return query
  select d.cloud_id, d.employee_username, d.day_date, d.status, d.started_at, d.ended_at, d.updated_at
  from public.dsp_attendance_days d
  -- 35-day buffer, 5 days past the app's own 30-day local retention, so a
  -- locally-purged record never gets silently re-pulled and looks "active"
  -- again the next time cloud sync runs.
  where d.day_date >= (now() - interval '35 days')::date
  order by d.updated_at desc, d.started_at desc
  limit 3000;
end;
$$;

create or replace function public.dsp_list_attendance_shifts(admin_secret text)
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
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  return query
  select s.cloud_id, s.employee_username, s.shift_date, s.shift_number, s.status, s.started_at, s.ended_at,
         s.break_count, s.total_break_seconds, s.current_break_started_at, s.updated_at
  from public.dsp_attendance_shifts s
  where s.shift_date >= (now() - interval '35 days')::date
  order by s.updated_at desc, s.started_at desc
  limit 3000;
end;
$$;

create or replace function public.dsp_list_attendance_day_events(admin_secret text)
returns table (
  cloud_id text,
  day_cloud_id text,
  employee_username text,
  day_date date,
  event_type text,
  event_label text,
  event_time timestamptz,
  details text,
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  return query
  select e.cloud_id, e.day_cloud_id, e.employee_username, e.day_date, e.event_type, e.event_label,
         e.event_time, e.details, e.updated_at
  from public.dsp_attendance_day_events e
  where e.day_date >= (now() - interval '35 days')::date
  order by e.event_time desc
  limit 5000;
end;
$$;

create or replace function public.dsp_list_attendance_events(admin_secret text)
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
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  return query
  select e.cloud_id, e.shift_cloud_id, e.employee_username, e.shift_date, e.shift_number,
         e.event_type, e.event_label, e.event_time, e.details, e.updated_at
  from public.dsp_attendance_events e
  where e.shift_date >= (now() - interval '35 days')::date
  order by e.event_time desc
  limit 5000;
end;
$$;
grant execute on function public.dsp_admin_secret_valid(text) to anon;
grant execute on function public.dsp_employee_sync_secret_valid(text) to anon;
grant execute on function public.dsp_upsert_employee_user(text, jsonb) to anon;
grant execute on function public.dsp_list_employee_users(text) to anon;
grant execute on function public.dsp_upsert_service_catalog_item(text, jsonb) to anon;
grant execute on function public.dsp_upsert_inventory_item(text, jsonb) to anon;
grant execute on function public.dsp_list_inventory_items(text) to anon;
grant execute on function public.dsp_upsert_attendance_day(text, jsonb) to anon;
grant execute on function public.dsp_upsert_attendance_shift(text, jsonb) to anon;
grant execute on function public.dsp_upsert_attendance_day_event(text, jsonb) to anon;
grant execute on function public.dsp_upsert_attendance_event(text, jsonb) to anon;
grant execute on function public.dsp_list_attendance_days(text) to anon;
grant execute on function public.dsp_list_attendance_shifts(text) to anon;
grant execute on function public.dsp_list_attendance_day_events(text) to anon;
grant execute on function public.dsp_list_attendance_events(text) to anon;
grant execute on function public.dsp_upsert_announcement(text, jsonb) to anon;

-- App settings sync (admin-controlled, machine-local settings such as the
-- sales workbook target) so a value saved once on the admin PC reaches every
-- installed employee app, instead of staying stuck in that one PC's local
-- SQLite file.
create table if not exists public.dsp_app_settings (
  setting_key text primary key,
  setting_value text not null default '',
  updated_at timestamptz not null default now()
);

alter table public.dsp_app_settings enable row level security;
revoke all on table public.dsp_app_settings from anon, authenticated;

create or replace function public.dsp_upsert_app_setting(admin_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  key_value := trim(coalesce(row_data->>'setting_key', ''));
  if key_value = '' then
    raise exception 'Setting key is required' using errcode = '22023';
  end if;

  insert into public.dsp_app_settings (setting_key, setting_value, updated_at)
  values (
    key_value,
    coalesce(row_data->>'setting_value', ''),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now())
  )
  on conflict (setting_key) do update set
    setting_value = excluded.setting_value,
    updated_at = excluded.updated_at;
end;
$$;

create or replace function public.dsp_list_app_settings(sync_secret text)
returns table (
  setting_key text,
  setting_value text,
  updated_at timestamptz
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
  select s.setting_key, s.setting_value, s.updated_at
  from public.dsp_app_settings s;
end;
$$;

-- Sales entries sync, so an employee's sold-item entries show up on the
-- admin's Sales Data tab/dashboard from any PC, not only on whichever
-- machine the employee used. Employees only ever push their own entries up
-- (via the employee sync secret); only the admin secret can pull the full
-- list back down, matching the attendance sync pattern. Contains customer
-- name/phone/email, so this table is never directly readable by anon - only
-- through these secret-gated functions.
create table if not exists public.dsp_sales_entries (
  cloud_id text primary key,
  employee_username text not null default '',
  entry_date date not null,
  entry_time text not null default '',
  customer text not null default '',
  item text not null default '',
  order_id text not null default '',
  buying_amount text not null default '',
  selling_amount text not null default '',
  profit text not null default '',
  status text not null default '',
  notes text not null default '',
  excel_row integer,
  excel_synced_at text not null default '',
  excel_sync_error text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists dsp_sales_entries_lookup_idx
on public.dsp_sales_entries (employee_username, entry_date desc, updated_at desc);

alter table public.dsp_sales_entries enable row level security;
revoke all on table public.dsp_sales_entries from anon, authenticated;

create or replace function public.dsp_upsert_sales_entry(sync_secret text, row_data jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  key_value text;
begin
  if not public.dsp_employee_sync_secret_valid(sync_secret) then
    raise exception 'Invalid employee sync secret' using errcode = '28000';
  end if;

  key_value := trim(coalesce(row_data->>'cloud_id', ''));
  if key_value = '' then
    raise exception 'Sales entry cloud_id is required' using errcode = '22023';
  end if;

  insert into public.dsp_sales_entries (
    cloud_id, employee_username, entry_date, entry_time, customer, item, order_id,
    buying_amount, selling_amount, profit, status, notes,
    excel_row, excel_synced_at, excel_sync_error, created_at, updated_at
  )
  values (
    key_value,
    coalesce(row_data->>'employee_username', ''),
    coalesce(nullif(row_data->>'entry_date', '')::date, now()::date),
    coalesce(row_data->>'entry_time', ''),
    coalesce(row_data->>'customer', ''),
    coalesce(row_data->>'item', ''),
    coalesce(row_data->>'order_id', ''),
    coalesce(row_data->>'buying_amount', ''),
    coalesce(row_data->>'selling_amount', ''),
    coalesce(row_data->>'profit', ''),
    coalesce(row_data->>'status', ''),
    coalesce(row_data->>'notes', ''),
    nullif(row_data->>'excel_row', '')::integer,
    coalesce(row_data->>'excel_synced_at', ''),
    coalesce(row_data->>'excel_sync_error', ''),
    coalesce(nullif(row_data->>'created_at', '')::timestamptz, now()),
    coalesce(nullif(row_data->>'updated_at', '')::timestamptz, now())
  )
  on conflict (cloud_id) do update set
    employee_username = excluded.employee_username,
    entry_date = excluded.entry_date,
    entry_time = excluded.entry_time,
    customer = excluded.customer,
    item = excluded.item,
    order_id = excluded.order_id,
    buying_amount = excluded.buying_amount,
    selling_amount = excluded.selling_amount,
    profit = excluded.profit,
    status = excluded.status,
    notes = excluded.notes,
    excel_row = excluded.excel_row,
    excel_synced_at = excluded.excel_synced_at,
    excel_sync_error = excluded.excel_sync_error,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at;
end;
$$;

create or replace function public.dsp_list_sales_entries(admin_secret text)
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
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  return query
  select s.cloud_id, s.employee_username, s.entry_date, s.entry_time, s.customer, s.item, s.order_id,
         s.buying_amount, s.selling_amount, s.profit, s.status, s.notes,
         s.excel_row, s.excel_synced_at, s.excel_sync_error, s.created_at, s.updated_at
  from public.dsp_sales_entries s
  order by s.entry_date desc, s.updated_at desc
  limit 5000;
end;
$$;

grant execute on function public.dsp_upsert_app_setting(text, jsonb) to anon;
grant execute on function public.dsp_list_app_settings(text) to anon;
grant execute on function public.dsp_upsert_sales_entry(text, jsonb) to anon;
grant execute on function public.dsp_list_sales_entries(text) to anon;
grant execute on function public.dsp_upsert_service_message_template(text, jsonb) to anon;

-- Lets the admin panel delete a stuck/test attendance shift permanently
-- instead of it silently reappearing on the next cloud sync pull. Deletion
-- intentionally needs the admin secret, not just the employee sync secret -
-- this is a destructive, owner-only action.
create or replace function public.dsp_delete_attendance_shift(admin_secret text, target_cloud_id text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;

  delete from public.dsp_attendance_events where shift_cloud_id = target_cloud_id;
  delete from public.dsp_attendance_shifts where cloud_id = target_cloud_id;
end;
$$;

grant execute on function public.dsp_delete_attendance_shift(text, text) to anon;