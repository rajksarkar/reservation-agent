-- Add Musaafer back with known release schedule
insert into public.restaurants (name, platform, venue_id, city, cuisine, neighborhood, price_range, release_time, release_days_ahead, release_schedule_notes) values
  ('Musaafer', 'opentable', 'musaafer-new-york-new-york-city', 'New York', 'Indian', 'TriBeCa', 3, '12:00', 14, null)
on conflict (platform, venue_id) do update set
  name = excluded.name,
  release_time = excluded.release_time,
  release_days_ahead = excluded.release_days_ahead;
