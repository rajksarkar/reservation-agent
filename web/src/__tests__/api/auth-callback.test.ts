import { describe, it, expect, vi, beforeEach } from "vitest";

const mockExchangeCode = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(async () => ({
    auth: {
      exchangeCodeForSession: mockExchangeCode,
    },
  })),
}));

describe("GET /auth/callback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("redirects to /dashboard on successful code exchange", async () => {
    mockExchangeCode.mockResolvedValue({ error: null });
    const { GET } = await import("@/app/auth/callback/route");
    const req = new Request("http://localhost/auth/callback?code=valid-code");
    const res = await GET(req);

    expect(res.status).toBe(307); // NextResponse.redirect
    expect(new URL(res.headers.get("location")!).pathname).toBe("/dashboard");
  });

  it("redirects to custom next path", async () => {
    mockExchangeCode.mockResolvedValue({ error: null });
    const { GET } = await import("@/app/auth/callback/route");
    const req = new Request("http://localhost/auth/callback?code=valid-code&next=/dashboard/settings");
    const res = await GET(req);

    expect(new URL(res.headers.get("location")!).pathname).toBe("/dashboard/settings");
  });

  it("redirects to /login on error", async () => {
    mockExchangeCode.mockResolvedValue({ error: { message: "bad code" } });
    const { GET } = await import("@/app/auth/callback/route");
    const req = new Request("http://localhost/auth/callback?code=bad-code");
    const res = await GET(req);

    const location = new URL(res.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("error")).toBe("auth_callback_error");
  });

  it("redirects to /login when no code provided", async () => {
    const { GET } = await import("@/app/auth/callback/route");
    const req = new Request("http://localhost/auth/callback");
    const res = await GET(req);

    const location = new URL(res.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("error")).toBe("auth_callback_error");
  });

  it("redirect URL uses the request origin (not a container hostname)", async () => {
    mockExchangeCode.mockResolvedValue({ error: null });
    const { GET } = await import("@/app/auth/callback/route");
    const req = new Request("https://myapp.example.com/auth/callback?code=valid-code");
    const res = await GET(req);

    const location = new URL(res.headers.get("location")!);
    expect(location.hostname).toBe("myapp.example.com");
    // Must NOT redirect to a Docker container hostname
    expect(location.hostname).not.toMatch(/^[a-f0-9]{12}$/);
  });
});
