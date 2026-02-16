import { describe, it, expect, vi, beforeEach } from "vitest";

// Set env before imports
process.env.NEXT_PUBLIC_SUPABASE_URL = "https://test.supabase.co";
process.env.SUPABASE_SERVICE_ROLE_KEY = "test-service-role-key";

const mockFrom = vi.fn();

vi.mock("@supabase/ssr", () => ({
  createServerClient: vi.fn(() => ({
    from: mockFrom,
  })),
}));

function makeRequest(body: object, authHeader?: string) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (authHeader) headers["Authorization"] = authHeader;
  return new Request("http://localhost/api/webhooks/worker-update", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

describe("POST /api/webhooks/worker-update", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 401 without auth header", async () => {
    const { POST } = await import("@/app/api/webhooks/worker-update/route");
    const req = makeRequest({ type: "attempt" });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("returns 401 with wrong token", async () => {
    const { POST } = await import("@/app/api/webhooks/worker-update/route");
    const req = makeRequest({ type: "attempt" }, "Bearer wrong-key");
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("handles attempt event type", async () => {
    const mockInsert = vi.fn().mockResolvedValue({ error: null });
    mockFrom.mockReturnValue({ insert: mockInsert });

    const { POST } = await import("@/app/api/webhooks/worker-update/route");
    const req = makeRequest(
      {
        type: "attempt",
        request_id: "req-1",
        data: {
          attempt_type: "cancellation_check",
          result: "no_availability",
          duration_ms: 1500,
        },
      },
      `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}`
    );
    const res = await POST(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
  });

  it("handles status_update event type", async () => {
    const mockUpdate = vi.fn().mockReturnValue({
      eq: vi.fn().mockResolvedValue({ error: null }),
    });
    const mockInsert = vi.fn().mockResolvedValue({ error: null });
    mockFrom.mockReturnValue({ update: mockUpdate, insert: mockInsert });

    const { POST } = await import("@/app/api/webhooks/worker-update/route");
    const req = makeRequest(
      {
        type: "status_update",
        request_id: "req-1",
        user_id: "user-1",
        data: {
          status: "booked",
          booked_date: "2026-04-01",
          booked_time: "19:30",
          confirmation_number: "CONF-1",
        },
      },
      `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}`
    );
    const res = await POST(req);
    expect(res.status).toBe(200);
  });

  it("returns 400 for unknown event type", async () => {
    const { POST } = await import("@/app/api/webhooks/worker-update/route");
    const req = makeRequest(
      { type: "unknown", request_id: "req-1", data: {} },
      `Bearer ${process.env.SUPABASE_SERVICE_ROLE_KEY}`
    );
    const res = await POST(req);
    expect(res.status).toBe(400);
  });
});
