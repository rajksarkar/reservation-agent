import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  // Verify worker secret
  const authHeader = request.headers.get("authorization");
  const expectedToken = `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}`;

  if (authHeader !== expectedToken) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Use service role client for worker updates
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    {
      cookies: {
        getAll: () => [],
        setAll: () => {},
      },
    }
  );

  const body = await request.json();
  const { type, request_id, user_id, data } = body;

  switch (type) {
    case "attempt": {
      await supabase.from("booking_attempts").insert({
        request_id,
        attempt_type: data.attempt_type,
        result: data.result,
        slot_time: data.slot_time || null,
        error_message: data.error_message || null,
        duration_ms: data.duration_ms || null,
      });
      break;
    }

    case "status_update": {
      const updates: Record<string, unknown> = { status: data.status };
      if (data.booked_date) updates.booked_date = data.booked_date;
      if (data.booked_time) updates.booked_time = data.booked_time;
      if (data.confirmation_number)
        updates.confirmation_number = data.confirmation_number;

      await supabase
        .from("reservation_requests")
        .update(updates)
        .eq("id", request_id);

      // Log activity
      if (user_id) {
        await supabase.from("activity_log").insert({
          user_id,
          request_id,
          event_type: `request_${data.status}`,
          title:
            data.status === "booked"
              ? "Reservation booked!"
              : `Request ${data.status}`,
          description: data.description || null,
        });
      }
      break;
    }

    default:
      return NextResponse.json({ error: "Unknown type" }, { status: 400 });
  }

  return NextResponse.json({ success: true });
}
