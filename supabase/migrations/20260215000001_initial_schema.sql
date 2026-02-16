-- ============================================================
-- Reservation Agent Web App - Initial Schema
-- ============================================================

-- Enable required extensions
create extension if not exists "pgcrypto";

-- ============================================================
-- 1. Profiles (1:1 with auth.users)
-- ============================================================
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  full_name text,
  avatar_url text,
  notification_email boolean not null default true,
  notification_sms boolean not null default false,
  phone text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "Users can view own profile"
  on public.profiles for select
  using (auth.uid() = id);

create policy "Users can update own profile"
  on public.profiles for update
  using (auth.uid() = id);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name', ''),
    coalesce(new.raw_user_meta_data ->> 'avatar_url', '')
  );
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================
-- 2. Platform Accounts (encrypted credentials per user)
-- ============================================================
create table public.platform_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  platform text not null check (platform in ('resy', 'opentable', 'tock')),
  encrypted_username text not null,
  encrypted_password text not null,
  encryption_iv text not null,
  encryption_tag text not null,
  is_connected boolean not null default true,
  last_verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, platform)
);

alter table public.platform_accounts enable row level security;

create policy "Users can view own platform accounts"
  on public.platform_accounts for select
  using (auth.uid() = user_id);

create policy "Users can insert own platform accounts"
  on public.platform_accounts for insert
  with check (auth.uid() = user_id);

create policy "Users can update own platform accounts"
  on public.platform_accounts for update
  using (auth.uid() = user_id);

create policy "Users can delete own platform accounts"
  on public.platform_accounts for delete
  using (auth.uid() = user_id);

-- ============================================================
-- 3. Restaurants (shared catalog)
-- ============================================================
create table public.restaurants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  platform text not null check (platform in ('resy', 'opentable', 'tock')),
  venue_id text not null,
  city text not null default 'New York',
  cuisine text,
  neighborhood text,
  price_range smallint check (price_range between 1 and 4),
  image_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(platform, venue_id)
);

alter table public.restaurants enable row level security;

create policy "Restaurants are publicly readable"
  on public.restaurants for select
  using (true);

-- ============================================================
-- 4. Reservation Requests
-- ============================================================
create type public.request_status as enum (
  'active', 'paused', 'booked', 'cancelled', 'expired'
);

create table public.reservation_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  restaurant_id uuid not null references public.restaurants(id),
  party_size smallint not null default 2 check (party_size between 1 and 20),
  target_dates date[] not null,
  preferred_times text[] not null,
  status public.request_status not null default 'active',
  monitor_cancellations boolean not null default true,
  release_snipe boolean not null default false,
  release_time time,
  release_days_ahead smallint,
  booked_date date,
  booked_time text,
  confirmation_number text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.reservation_requests enable row level security;

create policy "Users can view own requests"
  on public.reservation_requests for select
  using (auth.uid() = user_id);

create policy "Users can insert own requests"
  on public.reservation_requests for insert
  with check (auth.uid() = user_id);

create policy "Users can update own requests"
  on public.reservation_requests for update
  using (auth.uid() = user_id);

create policy "Users can delete own requests"
  on public.reservation_requests for delete
  using (auth.uid() = user_id);

-- Index for worker polling
create index idx_reservation_requests_active
  on public.reservation_requests (status)
  where status = 'active';

-- ============================================================
-- 5. Booking Attempts (log of each snipe/cancellation attempt)
-- ============================================================
create type public.attempt_type as enum ('snipe', 'cancellation_check', 'manual');

create type public.attempt_result as enum (
  'success', 'no_availability', 'slot_taken', 'auth_failed', 'error'
);

create table public.booking_attempts (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.reservation_requests(id) on delete cascade,
  attempt_type public.attempt_type not null,
  result public.attempt_result not null,
  slot_time text,
  error_message text,
  duration_ms integer,
  created_at timestamptz not null default now()
);

alter table public.booking_attempts enable row level security;

create policy "Users can view own attempts"
  on public.booking_attempts for select
  using (
    exists (
      select 1 from public.reservation_requests rr
      where rr.id = booking_attempts.request_id
      and rr.user_id = auth.uid()
    )
  );

-- Service role can insert (worker uses service role)
create policy "Service role can insert attempts"
  on public.booking_attempts for insert
  with check (true);

-- ============================================================
-- 6. Activity Log (user-facing feed)
-- ============================================================
create table public.activity_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  request_id uuid references public.reservation_requests(id) on delete set null,
  event_type text not null,
  title text not null,
  description text,
  metadata jsonb default '{}',
  created_at timestamptz not null default now()
);

alter table public.activity_log enable row level security;

create policy "Users can view own activity"
  on public.activity_log for select
  using (auth.uid() = user_id);

create policy "Service role can insert activity"
  on public.activity_log for insert
  with check (true);

-- ============================================================
-- Auto-update updated_at trigger
-- ============================================================
create or replace function public.update_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger update_profiles_updated_at
  before update on public.profiles
  for each row execute function public.update_updated_at();

create trigger update_platform_accounts_updated_at
  before update on public.platform_accounts
  for each row execute function public.update_updated_at();

create trigger update_restaurants_updated_at
  before update on public.restaurants
  for each row execute function public.update_updated_at();

create trigger update_reservation_requests_updated_at
  before update on public.reservation_requests
  for each row execute function public.update_updated_at();

-- ============================================================
-- Seed Data: Popular NYC Restaurants
-- ============================================================
insert into public.restaurants (name, platform, venue_id, city, cuisine, neighborhood, price_range) values
  ('Carbone', 'resy', 'carbone-new-york', 'New York', 'Italian', 'Greenwich Village', 4),
  ('Don Angie', 'resy', 'don-angie-new-york', 'New York', 'Italian', 'West Village', 3),
  ('4 Charles Prime Rib', 'resy', '4-charles-prime-rib-new-york', 'New York', 'Steakhouse', 'West Village', 4),
  ('Via Carota', 'resy', 'via-carota-new-york', 'New York', 'Italian', 'West Village', 3),
  ('Lilia', 'resy', 'lilia-brooklyn', 'New York', 'Italian', 'Williamsburg', 3),
  ('I Sodi', 'resy', 'i-sodi-new-york', 'New York', 'Italian', 'West Village', 3),
  ('Double Chicken Please', 'resy', 'double-chicken-please-new-york', 'New York', 'Cocktail Bar', 'Lower East Side', 2),
  ('Tatiana', 'resy', 'tatiana-new-york', 'New York', 'American', 'Lincoln Center', 3),
  ('Le Coucou', 'resy', 'le-coucou-new-york', 'New York', 'French', 'SoHo', 4),
  ('Musaafer', 'opentable', 'musaafer-new-york-new-york-city', 'New York', 'Indian', 'TriBeCa', 3),
  ('Peter Luger', 'opentable', 'peter-luger-steak-house-brooklyn', 'New York', 'Steakhouse', 'Williamsburg', 4),
  ('Le Bernardin', 'opentable', 'le-bernardin-new-york', 'New York', 'French/Seafood', 'Midtown', 4),
  ('Daniel', 'opentable', 'daniel-new-york', 'New York', 'French', 'Upper East Side', 4),
  ('Eleven Madison Park', 'tock', 'eleven-madison-park', 'New York', 'American', 'Flatiron', 4),
  ('Atomix', 'tock', 'atomix', 'New York', 'Korean', 'Midtown', 4),
  ('Chef''s Table at Brooklyn Fare', 'tock', 'chefs-table-brooklyn-fare', 'New York', 'French/Japanese', 'Hell''s Kitchen', 4)
on conflict (platform, venue_id) do nothing;
