import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET(request: Request) {
  const supabase = await createClient();
  const { searchParams } = new URL(request.url);
  const query = searchParams.get("q") || "";
  const platform = searchParams.get("platform");

  let q = supabase
    .from("restaurants")
    .select("id, name, platform, venue_id, city, cuisine, neighborhood, price_range")
    .order("name");

  if (query) {
    q = q.ilike("name", `%${query}%`);
  }
  if (platform) {
    q = q.eq("platform", platform);
  }

  const { data, error } = await q.limit(50);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
