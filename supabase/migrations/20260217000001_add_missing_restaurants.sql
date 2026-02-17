-- ============================================================
-- Add missing restaurants from nycrsvps.com reference data
-- and remove restaurants without known release schedules
-- Source: nycrsvps.com (updated 2026-02-16)
-- ============================================================

-- Add 4 restaurants that were missing from the DB
insert into public.restaurants (name, platform, venue_id, city, cuisine, neighborhood, price_range, release_time, release_days_ahead, release_schedule_notes) values
  ('Din Tai Fung', 'yelp', 'din-tai-fung-new-york', 'New York', 'Chinese', 'Midtown West', 2, '00:00', 30, null),
  ('Hillstone', 'own_site', 'hillstone-new-york', 'New York', 'American', 'Rose Hill', 3, '00:00', 30, null),
  ('Polo Bar', 'phone', 'polo-bar-new-york', 'New York', 'American', 'Midtown East', 4, '10:00', 30, null),
  ('The Corner Store', 'own_site', 'the-corner-store-new-york', 'New York', 'American', 'SoHo', 2, '10:00', 13, null)
on conflict (platform, venue_id) do update set
  name = excluded.name,
  cuisine = excluded.cuisine,
  neighborhood = excluded.neighborhood,
  price_range = excluded.price_range,
  release_time = excluded.release_time,
  release_days_ahead = excluded.release_days_ahead,
  release_schedule_notes = excluded.release_schedule_notes;

-- Remove restaurants that have no known release schedule data
-- (not tracked by nycrsvps.com, so snipe functionality won't work for them)
delete from public.restaurants where name in (
  'Musaafer',
  'Le Bernardin',
  'Daniel',
  'Atomix',
  'Chef''s Table at Brooklyn Fare'
) and release_time is null and release_days_ahead is null and release_schedule_notes is null;
