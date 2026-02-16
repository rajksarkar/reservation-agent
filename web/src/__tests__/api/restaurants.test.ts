import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFrom = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(async () => ({
    auth: { getUser: vi.fn() },
    from: mockFrom,
  })),
}));

describe("GET /api/restaurants", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns restaurants without filters", async () => {
    const mockData = [
      { id: "1", name: "Le Bernardin", platform: "resy" },
      { id: "2", name: "Eleven Madison Park", platform: "tock" },
    ];

    const mockLimit = vi.fn().mockResolvedValue({ data: mockData, error: null });
    const mockOrder = vi.fn().mockReturnValue({ limit: mockLimit });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({ order: mockOrder }),
    });

    const { GET } = await import("@/app/api/restaurants/route");
    const req = new Request("http://localhost/api/restaurants");
    const res = await GET(req);

    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json).toEqual(mockData);
  });

  it("filters by name search query", async () => {
    const mockLimit = vi.fn().mockResolvedValue({ data: [], error: null });
    const mockIlike = vi.fn().mockReturnValue({ limit: mockLimit });
    const mockOrder = vi.fn().mockReturnValue({ ilike: mockIlike, limit: mockLimit });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({ order: mockOrder }),
    });

    const { GET } = await import("@/app/api/restaurants/route");
    const req = new Request("http://localhost/api/restaurants?q=bernar");
    const res = await GET(req);
    expect(res.status).toBe(200);
  });

  it("filters by platform", async () => {
    const mockLimit = vi.fn().mockResolvedValue({ data: [], error: null });
    const mockEq = vi.fn().mockReturnValue({ limit: mockLimit });
    const mockOrder = vi.fn().mockReturnValue({ eq: mockEq, limit: mockLimit });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({ order: mockOrder }),
    });

    const { GET } = await import("@/app/api/restaurants/route");
    const req = new Request("http://localhost/api/restaurants?platform=resy");
    const res = await GET(req);
    expect(res.status).toBe(200);
  });

  it("returns 500 on database error", async () => {
    const mockLimit = vi.fn().mockResolvedValue({ data: null, error: { message: "DB error" } });
    const mockOrder = vi.fn().mockReturnValue({ limit: mockLimit });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({ order: mockOrder }),
    });

    const { GET } = await import("@/app/api/restaurants/route");
    const req = new Request("http://localhost/api/restaurants");
    const res = await GET(req);
    expect(res.status).toBe(500);
  });
});
