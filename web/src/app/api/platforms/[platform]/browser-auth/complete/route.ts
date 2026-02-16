import { createClient } from "@/lib/supabase/server";
import { completeBrowserAuth, cancelBrowserAuth } from "@/lib/browserbase";
import { NextResponse } from "next/server";

export async function POST(
  request: Request,
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

  const { authSessionId } = await request.json();
  if (!authSessionId) {
    return NextResponse.json({ error: "authSessionId is required" }, { status: 400 });
  }

  try {
    const { storageState, platform: sessionPlatform, userId } = await completeBrowserAuth(authSessionId);

    // Verify the session belongs to this user and platform
    if (userId !== user.id || sessionPlatform !== platform) {
      return NextResponse.json({ error: "Session mismatch" }, { status: 403 });
    }

    // Upsert platform account with session data (no encrypted credentials needed)
    const { error } = await supabase
      .from("platform_accounts")
      .upsert(
        {
          user_id: user.id,
          platform,
          session_data: storageState,
          is_connected: true,
          last_verified_at: new Date().toISOString(),
        },
        { onConflict: "user_id,platform" }
      );

    if (error) {
      console.error("Supabase upsert error:", error);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // Log activity
    await supabase.from("activity_log").insert({
      user_id: user.id,
      event_type: "platform_connected",
      title: `Connected ${platform} via browser login`,
      description: "Platform session captured from browser authentication",
    });

    return NextResponse.json({ success: true, platform });
  } catch (err) {
    console.error("Failed to complete browser auth:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to capture session" },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: Request,
) {
  const { authSessionId } = await request.json();
  if (authSessionId) {
    await cancelBrowserAuth(authSessionId);
  }
  return NextResponse.json({ success: true });
}
