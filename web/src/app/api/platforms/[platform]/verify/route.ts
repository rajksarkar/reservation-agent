import { createClient } from "@/lib/supabase/server";
import { decrypt } from "@/lib/crypto";
import { NextResponse } from "next/server";

export async function GET(
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

  const { data: account, error } = await supabase
    .from("platform_accounts")
    .select("id, platform, encrypted_username, encryption_iv, encryption_tag, is_connected, last_verified_at")
    .eq("user_id", user.id)
    .eq("platform", platform)
    .single();

  if (error || !account) {
    return NextResponse.json({ error: "No account found" }, { status: 404 });
  }

  try {
    const [usernameIv, passwordIv] = account.encryption_iv.split("|");
    const [usernameTag, passwordTag] = account.encryption_tag.split("|");

    // Decrypt username to verify credentials can be retrieved
    const username = decrypt(account.encrypted_username, usernameIv, usernameTag, user.id);

    return NextResponse.json({
      platform: account.platform,
      username,
      is_connected: account.is_connected,
      last_verified_at: account.last_verified_at,
      verified: true,
    });
  } catch {
    return NextResponse.json(
      { error: "Failed to decrypt credentials. Please reconnect your account.", verified: false },
      { status: 500 }
    );
  }
}
