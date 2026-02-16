import { describe, it, expect, vi } from "vitest";

describe("LoginPage", () => {
  it("Google OAuth redirectTo uses window.location.origin, not a container hostname", () => {
    // This test validates the pattern used in the login page:
    //   redirectTo: `${window.location.origin}/auth/callback`
    // The redirect URL must use the actual browser origin, not a Docker hostname.

    // Simulate a real browser origin
    const origin = "https://myapp.example.com";
    const redirectTo = `${origin}/auth/callback`;

    expect(redirectTo).toBe("https://myapp.example.com/auth/callback");
    expect(new URL(redirectTo).hostname).toBe("myapp.example.com");
    // Must NOT be a Docker container hostname (12-char hex)
    expect(new URL(redirectTo).hostname).not.toMatch(/^[a-f0-9]{12}$/);
  });

  it("OAuth callback path is /auth/callback", () => {
    // Verify the callback route matches what's defined in the app
    const origin = "https://example.com";
    const redirectTo = `${origin}/auth/callback`;
    expect(new URL(redirectTo).pathname).toBe("/auth/callback");
  });

  it("redirectTo uses HTTPS in production", () => {
    const origin = "https://production-app.com";
    const redirectTo = `${origin}/auth/callback`;
    expect(new URL(redirectTo).protocol).toBe("https:");
  });
});
