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

  const { data, error } = await supabase
    .from("reservation_requests")
    .insert({
      user_id: user.id,
      restaurant_id,
      party_size: party_size || 2,
      target_dates,
      preferred_times,
      monitor_cancellations: monitor_cancellations ?? true,
      release_snipe: release_snipe ?? false,
      release_time: release_time || null,
      release_days_ahead: release_days_ahead || null,
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
