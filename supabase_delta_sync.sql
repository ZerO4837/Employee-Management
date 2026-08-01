-- =====================================================================
-- Delta sync (v2.0.5): every list function gains a "_delta" variant that
-- returns ONLY rows changed after `since`, so the apps stop re-downloading
-- entire tables every sync cycle (the cause of the egress overage).
-- The original functions stay untouched - older app versions keep working,
-- and new versions fall back to them automatically until this is applied.
-- Run this whole script once in Supabase -> SQL Editor.
-- =====================================================================

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
  deleted_at timestamptz
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
         u.password_hash, u.created_at, u.updated_at, u.deleted_at
  from public.dsp_employee_users u
  where (cutoff is null or u.updated_at > cutoff)
  order by u.updated_at desc, u.username_key asc;
end;
$$;

create or replace function public.dsp_list_inventory_items_delta(sync_secret text, since text)
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
         i.created_by, i.created_at, i.updated_at, i.is_active
  from public.dsp_inventory_items i
  where (cutoff is null or i.updated_at > cutoff)
  order by i.service_name asc, i.account_email asc, i.updated_at desc;
end;
$$;

create or replace function public.dsp_list_app_settings_delta(sync_secret text, since text)
returns table (
  setting_key text,
  setting_value text,
  updated_at timestamptz
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
  select s.setting_key, s.setting_value, s.updated_at
  from public.dsp_app_settings s
  where (cutoff is null or s.updated_at > cutoff);
end;
$$;

create or replace function public.dsp_list_attendance_days_delta(admin_secret text, since text)
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
declare cutoff timestamptz;
begin
  if not public.dsp_admin_secret_valid(admin_secret) then
    raise exception 'Invalid admin sync secret' using errcode = '28000';
  end if;
  if coalesce(since, '') <> '' then
    cutoff := since::timestamptz;
  end if;
  return query
  select d.cloud_id, d.employee_username, d.day_date, d.status, d.started_at, d.ended_at, d.updated_at
  from public.dsp_attendance_days d
  where d.day_date >= (now() - interval '35 days')::date
    and (cutoff is null or d.updated_at > cutoff)
  order by d.updated_at desc, d.started_at desc
  limit 3000;
end;
$$;

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
  updated_at timestamptz
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
         s.break_count, s.total_break_seconds, s.current_break_started_at, s.updated_at
  from public.dsp_attendance_shifts s
  where s.shift_date >= (now() - interval '35 days')::date
    and (cutoff is null or s.updated_at > cutoff)
  order by s.updated_at desc, s.started_at desc
  limit 3000;
end;
$$;

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
  updated_at timestamptz
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
         e.event_time, e.details, e.updated_at
  from public.dsp_attendance_day_events e
  where e.day_date >= (now() - interval '35 days')::date
    and (cutoff is null or e.updated_at > cutoff)
  order by e.event_time desc
  limit 5000;
end;
$$;

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
  updated_at timestamptz
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
         e.event_type, e.event_label, e.event_time, e.details, e.updated_at
  from public.dsp_attendance_events e
  where e.shift_date >= (now() - interval '35 days')::date
    and (cutoff is null or e.updated_at > cutoff)
  order by e.event_time desc
  limit 5000;
end;
$$;

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
  updated_at timestamptz
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
         s.excel_row, s.excel_synced_at, s.excel_sync_error, s.created_at, s.updated_at
  from public.dsp_sales_entries s
  where (cutoff is null or s.updated_at > cutoff)
  order by s.entry_date desc, s.updated_at desc
  limit 5000;
end;
$$;

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
  updated_at timestamptz
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
         s.excel_row, s.excel_synced_at, s.excel_sync_error, s.created_at, s.updated_at
  from public.dsp_sales_entries s
  where (cutoff is null or s.updated_at > cutoff)
  order by s.entry_date desc, s.updated_at desc
  limit 5000;
end;
$$;

grant execute on function public.dsp_list_employee_users_delta(text, text) to anon;
grant execute on function public.dsp_list_inventory_items_delta(text, text) to anon;
grant execute on function public.dsp_list_app_settings_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_days_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_shifts_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_day_events_delta(text, text) to anon;
grant execute on function public.dsp_list_attendance_events_delta(text, text) to anon;
grant execute on function public.dsp_list_sales_entries_delta(text, text) to anon;
grant execute on function public.dsp_list_sales_entries_shared_delta(text, text) to anon;
