-- ============================================================
-- Add release schedule columns to restaurants + expanded seed data
-- Source: nycrsvps.com (scraped 2026-02-15)
-- ============================================================

-- Add release schedule fields
alter table public.restaurants
  add column if not exists release_time time,
  add column if not exists release_days_ahead smallint,
  add column if not exists release_schedule_notes text;

-- Relax platform check to allow additional platforms
alter table public.restaurants
  drop constraint if exists restaurants_platform_check;

alter table public.restaurants
  add constraint restaurants_platform_check
  check (platform in ('resy', 'opentable', 'tock', 'yelp', 'phone', 'own_site'));

-- Clear old seed data and insert comprehensive list
delete from public.restaurants;

insert into public.restaurants (name, platform, venue_id, city, cuisine, neighborhood, price_range, release_time, release_days_ahead, release_schedule_notes) values
  -- Resy restaurants
  ('4 Charles Prime Rib', 'resy', '4-charles-prime-rib-new-york', 'New York', 'Steakhouse', 'West Village', 4, '09:00', 20, null),
  ('Adda', 'resy', 'adda-new-york', 'New York', 'Indian', 'East Village', 2, '09:00', 6, null),
  ('Atoboy', 'resy', 'atoboy-new-york', 'New York', 'Korean', 'NoMad', 3, '00:00', 29, null),
  ('Au Cheval', 'resy', 'au-cheval-new-york', 'New York', 'American', 'Tribeca', 3, '09:00', 20, null),
  ('Balthazar', 'resy', 'balthazar-new-york', 'New York', 'French', 'SoHo', 3, '00:00', 30, null),
  ('Bistrot Ha', 'resy', 'bistrot-ha-new-york', 'New York', 'French Vietnamese', 'Lower East Side', 2, '00:00', 6, null),
  ('Bonnie''s', 'resy', 'bonnies-brooklyn', 'New York', 'Cantonese', 'Williamsburg', 2, '10:00', 13, null),
  ('Bungalow', 'resy', 'bungalow-new-york', 'New York', 'Indian', 'East Village', 2, '11:00', 20, null),
  ('Buvette', 'resy', 'buvette-new-york', 'New York', 'French', 'West Village', 3, '10:00', 13, null),
  ('Carbone', 'resy', 'carbone-new-york', 'New York', 'Italian', 'Greenwich Village', 4, '10:00', 30, null),
  ('Chinese Tuxedo', 'resy', 'chinese-tuxedo-new-york', 'New York', 'Chinese', 'Chinatown', 3, '00:00', 14, null),
  ('Claud', 'resy', 'claud-new-york', 'New York', 'European', 'East Village', 3, '00:00', 15, null),
  ('Corner Bar', 'resy', 'corner-bar-new-york', 'New York', 'American', 'Lower East Side', 2, '09:00', 27, null),
  ('Cote', 'resy', 'cote-new-york', 'New York', 'Korean', 'Chelsea', 4, '10:00', 29, null),
  ('Dhamaka', 'resy', 'dhamaka-new-york', 'New York', 'Indian', 'Lower East Side', 2, '09:00', 14, null),
  ('Double Chicken Please', 'resy', 'double-chicken-please-new-york', 'New York', 'Cocktails / New American', 'Lower East Side', 2, '00:00', 6, null),
  ('Eleven Madison Park', 'resy', 'eleven-madison-park-new-york', 'New York', 'New American', 'Flatiron', 4, '10:00', null, '1st of prev. month'),
  ('Fish Cheeks', 'resy', 'fish-cheeks-new-york', 'New York', 'Thai', 'Nolita', 3, '00:00', 29, null),
  ('Ha''s Snack Bar', 'resy', 'has-snack-bar-new-york', 'New York', 'Vietnamese', 'Lower East Side', 2, '12:00', 20, null),
  ('i Sodi', 'resy', 'i-sodi-new-york', 'New York', 'Italian', 'West Village', 3, '00:00', 13, null),
  ('L''Artusi', 'resy', 'lartusi-new-york', 'New York', 'Italian', 'West Village', 3, '09:00', 14, null),
  ('Laser Wolf', 'resy', 'laser-wolf-brooklyn', 'New York', 'Israeli', 'Williamsburg', 3, '10:00', 21, null),
  ('Le Cafe Louis Vuitton', 'resy', 'le-cafe-louis-vuitton-new-york', 'New York', 'French', 'Midtown East', 4, '00:00', 27, null),
  ('Lilia', 'resy', 'lilia-brooklyn', 'New York', 'Italian', 'Williamsburg', 3, '10:00', 28, null),
  ('Masalawala & Sons', 'resy', 'masalawala-and-sons-brooklyn', 'New York', 'Indian', 'Park Slope', 2, '00:00', 14, null),
  ('Misi', 'resy', 'misi-brooklyn', 'New York', 'Italian', 'Williamsburg', 3, '10:00', 27, null),
  ('Monkey Bar', 'resy', 'monkey-bar-new-york', 'New York', 'American', 'Midtown East', 3, '09:00', 20, null),
  ('Peter Luger', 'resy', 'peter-luger-brooklyn', 'New York', 'Steakhouse', 'Williamsburg', 4, '00:00', 30, null),
  ('Raoul''s', 'resy', 'raouls-new-york', 'New York', 'French', 'Greenwich Village', 3, '08:00', 30, null),
  ('Red Hook Tavern', 'resy', 'red-hook-tavern-brooklyn', 'New York', 'American', 'Red Hook', 3, '00:00', 13, null),
  ('Rezdora', 'resy', 'rezdora-new-york', 'New York', 'Italian', 'Flatiron', 3, '00:00', 29, null),
  ('Rubirosa', 'resy', 'rubirosa-new-york', 'New York', 'Italian', 'Nolita', 2, '00:00', 7, null),
  ('Sadelle''s', 'resy', 'sadelles-new-york', 'New York', 'Brunch', 'SoHo', 3, '10:00', 30, null),
  ('Semma', 'resy', 'semma-new-york', 'New York', 'South Indian', 'Greenwich Village', 3, '09:00', 14, null),
  ('Shuka', 'resy', 'shuka-new-york', 'New York', 'Mediterranean', 'SoHo', 3, '00:00', 29, null),
  ('Sushi Nakazawa', 'resy', 'sushi-nakazawa-new-york', 'New York', 'Sushi', 'West Village', 4, '00:00', 14, null),
  ('Tatiana', 'resy', 'tatiana-new-york', 'New York', 'Afro-Caribbean', 'Upper West Side', 3, '12:00', 27, null),
  ('Thai Diner', 'resy', 'thai-diner-new-york', 'New York', 'Thai', 'Nolita', 2, '00:00', 29, null),
  ('The Four Horsemen', 'resy', 'the-four-horsemen-brooklyn', 'New York', 'Wine Bar', 'Williamsburg', 3, '07:00', 29, null),
  ('Theodora', 'resy', 'theodora-brooklyn', 'New York', 'Mediterranean', 'Fort Greene', 3, '09:00', 30, null),
  ('Torrisi Bar & Restaurant', 'resy', 'torrisi-new-york', 'New York', 'Italian', 'Nolita', 4, '10:00', 30, null),
  ('Via Carota', 'resy', 'via-carota-new-york', 'New York', 'Italian', 'West Village', 3, '10:00', 30, null),
  ('Waverly Inn', 'resy', 'waverly-inn-new-york', 'New York', 'American', 'West Village', 3, '08:00', 14, null),

  -- OpenTable restaurants
  ('Don Angie', 'opentable', 'don-angie-new-york', 'New York', 'Italian', 'West Village', 3, '09:00', 7, null),
  ('Gage & Tollner', 'opentable', 'gage-and-tollner-brooklyn', 'New York', 'American', 'Brooklyn', 3, '10:00', 30, null),
  ('Roscioli (Tasting Menu)', 'opentable', 'roscioli-new-york', 'New York', 'Italian', 'SoHo', 4, '10:00', 14, null),
  ('Una Pizza Napoletana', 'opentable', 'una-pizza-napoletana-new-york', 'New York', 'Pizza', 'Lower East Side', 2, '09:00', 14, null),
  ('Zou Zou''s', 'opentable', 'zou-zous-new-york', 'New York', 'Mediterranean', 'Hudson Yards', 3, '09:00', 21, null),
  ('Musaafer', 'opentable', 'musaafer-new-york-new-york-city', 'New York', 'Indian', 'TriBeCa', 3, null, null, null),
  ('Le Bernardin', 'opentable', 'le-bernardin-new-york', 'New York', 'French / Seafood', 'Midtown', 4, null, null, null),
  ('Daniel', 'opentable', 'daniel-new-york', 'New York', 'French', 'Upper East Side', 4, null, null, null),

  -- Tock restaurants
  ('Per Se', 'tock', 'per-se', 'New York', 'French', 'Columbus Circle', 4, '10:00', null, '1st of prev. month'),
  ('Atomix', 'tock', 'atomix', 'New York', 'Korean', 'Midtown', 4, null, null, null),
  ('Chef''s Table at Brooklyn Fare', 'tock', 'chefs-table-brooklyn-fare', 'New York', 'French / Japanese', 'Hell''s Kitchen', 4, null, null, null)

on conflict (platform, venue_id) do update set
  name = excluded.name,
  cuisine = excluded.cuisine,
  neighborhood = excluded.neighborhood,
  price_range = excluded.price_range,
  release_time = excluded.release_time,
  release_days_ahead = excluded.release_days_ahead,
  release_schedule_notes = excluded.release_schedule_notes;
