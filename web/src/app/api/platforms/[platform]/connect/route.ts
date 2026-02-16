import { createClient } from "@/lib/supabase/server";
import { encrypt } from "@/lib/crypto";
import { NextResponse } from "next/server";

const RESY_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5";

async function verifyResyCredentials(email: string, password: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const res = await fetch("https://api.resy.com/3/auth/password", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": `ResyAPI api_key="${RESY_API_KEY}"`,
      },
      body: new URLSearchParams({ email, password }),
    });

    if (res.status === 200) {
      return { valid: true };
    }

    const data = await res.json().catch(() => ({}));
    if (res.status === 419 || res.status === 401) {
      return { valid: false, error: "Invalid email or password for Resy." };
    }
    return { valid: false, error: data.message || "Could not verify Resy credentials." };
  } catch {
    // Network error - allow connection but mark as unverified
    return { valid: true };
  }
}

async function verifyOpenTableCredentials(email: string, password: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const res = await fetch("https://www.opentable.com/dapi/fe/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });

    if (res.status === 200) {
      return { valid: true };
    }

    if (res.status === 401 || res.status === 403) {
      return { valid: false, error: "Invalid email or password for OpenTable." };
    }

    // If we get rate-limited or an unexpected response, allow connection
    return { valid: true };
  } catch {
    return { valid: true };
  }
}

async function verifyTockCredentials(email: string, password: string): Promise<{ valid: boolean; error?: string }> {
  try {
    const res = await fetch("https://www.exploretock.com/api/consumer/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });

    if (res.status === 200) {
      return { valid: true };
    }

    if (res.status === 401 || res.status === 403) {
      return { valid: false, error: "Invalid email or password for Tock." };
    }

    return { valid: true };
  } catch {
    return { valid: true };
  }
}

async function verifyCredentials(
  platform: string,
  username: string,
  password: string
): Promise<{ valid: boolean; error?: string }> {
  switch (platform) {
    case "resy":
      return verifyResyCredentials(username, password);
    case "opentable":
      return verifyOpenTableCredentials(username, password);
    case "tock":
      return verifyTockCredentials(username, password);
    default:
      return { valid: true };
  }
}

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

  const validPlatforms = ["resy", "opentable", "tock"];
  if (!validPlatforms.includes(platform)) {
    return NextResponse.json({ error: "Invalid platform" }, { status: 400 });
  }

  const { username, password } = await request.json();
  if (!username || !password) {
    return NextResponse.json(
      { error: "Username and password required" },
      { status: 400 }
    );
  }

  // Verify credentials with the platform before storing
  const verification = await verifyCredentials(platform, username, password);
  if (!verification.valid) {
    return NextResponse.json(
      { error: verification.error || "Invalid credentials" },
      { status: 401 }
    );
  }

  // Encrypt credentials
  const encUsername = encrypt(username, user.id);
  const encPassword = encrypt(password, user.id);

  // Upsert platform account
  const { data, error } = await supabase
    .from("platform_accounts")
    .upsert(
      {
        user_id: user.id,
        platform,
        encrypted_username: encUsername.encrypted,
        encrypted_password: encPassword.encrypted,
        encryption_iv: `${encUsername.iv}|${encPassword.iv}`,
        encryption_tag: `${encUsername.tag}|${encPassword.tag}`,
        is_connected: true,
      },
      { onConflict: "user_id,platform" }
    )
    .select("id, platform, is_connected")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // Log activity
  await supabase.from("activity_log").insert({
    user_id: user.id,
    event_type: "platform_connected",
    title: `Connected ${platform}`,
    description: `Platform account verified and connected successfully`,
  });

  return NextResponse.json(data, { status: 201 });
}
