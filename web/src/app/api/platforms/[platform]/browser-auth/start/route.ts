import { createClient } from "@/lib/supabase/server";
import { startBrowserAuth } from "@/lib/browserbase";
import { NextResponse } from "next/server";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ platform: string }> }
) {
  const { platform } = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const validPlatforms = ["resy", "opentable", "tock"];
  if (!validPlatforms.includes(platform)) {
    return NextResponse.json({ error: "Invalid platform" }, { status: 400 });
  }

  if (!process.env.BROWSERBASE_API_KEY || !process.env.BROWSERBASE_PROJECT_ID) {
    return NextResponse.json(
      { error: "Browser auth is not configured. Missing BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID." },
      { status: 500 }
    );
  }

  try {
    const { authSessionId, liveViewUrl } = await startBrowserAuth(platform, user.id);

    return NextResponse.json({ authSessionId, liveViewUrl });
  } catch (err) {
    console.error("Failed to start browser auth:", err);
    return NextResponse.json(
      { error: "Failed to launch browser session. Please try again." },
      { status: 500 }
    );
  }
}
