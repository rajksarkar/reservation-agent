import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock Supabase before importing route handlers
const mockFrom = vi.fn();
const mockGetUser = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(async () => ({
    auth: { getUser: mockGetUser },
    from: mockFrom,
  })),
}));

const MOCK_USER = { id: "user-123", email: "test@example.com" };

function makeRequest(method: string, body?: object, url = "http://localhost/api/reservations") {
  return new Request(url, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

describe("GET /api/reservations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 401 when not authenticated", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    const { GET } = await import("@/app/api/reservations/route");
    const res = await GET();
    expect(res.status).toBe(401);
  });

  it("returns reservations for authenticated user", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const mockData = [{ id: "r1", status: "active" }];
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          order: vi.fn().mockResolvedValue({ data: mockData, error: null }),
        }),
      }),
    });

    const { GET } = await import("@/app/api/reservations/route");
    const res = await GET();
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json).toEqual(mockData);
  });
});

describe("POST /api/reservations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 401 when not authenticated", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    const { POST } = await import("@/app/api/reservations/route");
    const req = makeRequest("POST", { restaurant_id: "r1" });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("returns 400 when missing required fields", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const { POST } = await import("@/app/api/reservations/route");
    const req = makeRequest("POST", { restaurant_id: "r1" }); // missing target_dates and preferred_times
    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it("creates reservation and returns 201", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const insertedData = { id: "new-r1", status: "active" };

    mockFrom.mockReturnValue({
      insert: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          single: vi.fn().mockResolvedValue({ data: insertedData, error: null }),
        }),
      }),
    });

    const { POST } = await import("@/app/api/reservations/route");
    const req = makeRequest("POST", {
      restaurant_id: "rest-1",
      party_size: 2,
      target_dates: ["2026-04-01"],
      preferred_times: ["19:00-20:00"],
    });
    const res = await POST(req);
    expect(res.status).toBe(201);
  });
});

describe("GET /api/reservations/[id]", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 404 when not found", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            single: vi.fn().mockResolvedValue({ data: null, error: { message: "not found" } }),
          }),
        }),
      }),
    });

    const { GET } = await import("@/app/api/reservations/[id]/route");
    const res = await GET(
      makeRequest("GET"),
      { params: Promise.resolve({ id: "nonexistent" }) }
    );
    expect(res.status).toBe(404);
  });
});

describe("PATCH /api/reservations/[id]", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("updates allowed fields", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const updatedData = { id: "r1", status: "paused" };

    mockFrom.mockReturnValue({
      update: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              single: vi.fn().mockResolvedValue({ data: updatedData, error: null }),
            }),
          }),
        }),
      }),
      // For activity_log insert
      insert: vi.fn().mockResolvedValue({ error: null }),
    });

    const { PATCH } = await import("@/app/api/reservations/[id]/route");
    const req = makeRequest("PATCH", { status: "paused" });
    const res = await PATCH(req, { params: Promise.resolve({ id: "r1" }) });
    expect(res.status).toBe(200);
  });
});

describe("DELETE /api/reservations/[id]", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 401 when not authenticated", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    const { DELETE } = await import("@/app/api/reservations/[id]/route");
    const res = await DELETE(
      makeRequest("DELETE"),
      { params: Promise.resolve({ id: "r1" }) }
    );
    expect(res.status).toBe(401);
  });

  it("deletes and returns success", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    mockFrom.mockReturnValue({
      delete: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: null }),
        }),
      }),
    });

    const { DELETE } = await import("@/app/api/reservations/[id]/route");
    const res = await DELETE(
      makeRequest("DELETE"),
      { params: Promise.resolve({ id: "r1" }) }
    );
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.success).toBe(true);
  });
});
