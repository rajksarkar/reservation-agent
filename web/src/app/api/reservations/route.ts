import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { data, error } = await supabase
    .from("reservation_requests")
    .select("*, restaurants(name, platform, cuisine)")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}

export async function POST(request: Request) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();
  const {
    restaurant_id,
    party_size,
    target_dates,
    preferred_times,
    monitor_cancellations,
    release_snipe,
    release_time,
    release_days_ahead,
  } = body;

  if (!restaurant_id || !target_dates?.length || !preferred_times?.length) {
    return NextResponse.json(
      { error: "Missing required fields" },
      { status: 400 }
    );
  }

  // Look up restaurant release schedule to auto-fill snipe settings
  let resolvedSnipe = release_snipe ?? false;
  let resolvedReleaseTime = release_time || null;
  let resolvedReleaseDaysAhead = release_days_ahead || null;
  let resolvedMonitorCancellations = monitor_cancellations ?? true;

  if (!release_snipe) {
    const { data: restaurant } = await supabase
      .from("restaurants")
      .select("release_time, release_days_ahead")
      .eq("id", restaurant_id)
      .single();

    if (restaurant?.release_days_ahead) {
      resolvedReleaseDaysAhead = restaurant.release_days_ahead;
      resolvedReleaseTime = restaurant.release_time?.substring(0, 5) || "09:00";

      // Check if any target date is still unreleased
      const now = new Date();
      const hasUnreleased = target_dates.some((d: string) => {
        const target = new Date(d + "T00:00:00");
        const rParts = (resolvedReleaseTime as string).split(":").map(Number);
        const releaseDate = new Date(target);
        releaseDate.setDate(releaseDate.getDate() - restaurant.release_days_ahead);
        releaseDate.setHours(rParts[0], rParts[1], 0, 0);
        return now < releaseDate;
      });
      const hasReleased = target_dates.some((d: string) => {
        const target = new Date(d + "T00:00:00");
        const rParts = (resolvedReleaseTime as string).split(":").map(Number);
        const releaseDate = new Date(target);
        releaseDate.setDate(releaseDate.getDate() - restaurant.release_days_ahead);
        releaseDate.setHours(rParts[0], rParts[1], 0, 0);
        return now >= releaseDate;
      });

      if (hasUnreleased) {
        resolvedSnipe = true;
      }
      if (!hasReleased) {
        resolvedMonitorCancellations = false;
      }
    }
  }

  const { data, error } = await supabase
    .from("reservation_requests")
    .insert({
      user_id: user.id,
      restaurant_id,
      party_size: party_size || 2,
      target_dates,
      preferred_times,
      monitor_cancellations: resolvedMonitorCancellations,
      release_snipe: resolvedSnipe,
      release_time: resolvedReleaseTime,
      release_days_ahead: resolvedReleaseDaysAhead,
      status: "active",
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // Log activity
  await supabase.from("activity_log").insert({
    user_id: user.id,
    request_id: data.id,
    event_type: "request_created",
    title: "Reservation request created",
    description: `Monitoring ${target_dates.length} date(s) for party of ${party_size}`,
  });

  return NextResponse.json(data, { status: 201 });
}
