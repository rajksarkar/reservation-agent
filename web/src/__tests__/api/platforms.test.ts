import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFrom = vi.fn();
const mockGetUser = vi.fn();

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(async () => ({
    auth: { getUser: mockGetUser },
    from: mockFrom,
  })),
}));

vi.mock("@/lib/crypto", () => ({
  encrypt: vi.fn((value: string) => ({
    encrypted: `enc-${value}`,
    iv: `iv-${value}`,
    tag: `tag-${value}`,
  })),
  decrypt: vi.fn(
    (encrypted: string) => encrypted.replace("enc-", "")
  ),
}));

// Mock global fetch for credential verification
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const MOCK_USER = { id: "user-123", email: "test@example.com" };

function makeRequest(method: string, body?: object) {
  return new Request("http://localhost/api/platforms/resy/connect", {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

describe("POST /api/platforms/[platform]/connect", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: platform verification succeeds
    mockFetch.mockResolvedValue({ status: 200, json: async () => ({}) });
  });

  it("returns 401 when not authenticated", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    const { POST } = await import("@/app/api/platforms/[platform]/connect/route");
    const req = makeRequest("POST", { username: "u", password: "p" });
    const res = await POST(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(401);
  });

  it("returns 400 for invalid platform", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const { POST } = await import("@/app/api/platforms/[platform]/connect/route");
    const req = makeRequest("POST", { username: "u", password: "p" });
    const res = await POST(req, { params: Promise.resolve({ platform: "invalid" }) });
    expect(res.status).toBe(400);
  });

  it("returns 400 when missing credentials", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const { POST } = await import("@/app/api/platforms/[platform]/connect/route");
    const req = makeRequest("POST", { username: "" });
    const res = await POST(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(400);
  });

  it("encrypts and upserts on success", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });

    const upsertedData = { id: "acct-1", platform: "resy", is_connected: true };
    mockFrom.mockReturnValue({
      upsert: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          single: vi.fn().mockResolvedValue({ data: upsertedData, error: null }),
        }),
      }),
      insert: vi.fn().mockResolvedValue({ error: null }),
    });

    const { POST } = await import("@/app/api/platforms/[platform]/connect/route");
    const req = makeRequest("POST", { username: "user@test.com", password: "pass123" });
    const res = await POST(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(201);
  });

  it("returns 401 when platform credential verification fails", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    // Simulate Resy 419 (invalid credentials)
    mockFetch.mockResolvedValue({
      status: 419,
      json: async () => ({ message: "Invalid" }),
    });

    const { POST } = await import("@/app/api/platforms/[platform]/connect/route");
    const req = makeRequest("POST", { username: "bad@test.com", password: "wrong" });
    const res = await POST(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(401);
  });
});

describe("GET /api/platforms/[platform]/verify", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 401 when not authenticated", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    const { GET } = await import("@/app/api/platforms/[platform]/verify/route");
    const req = new Request("http://localhost/api/platforms/resy/verify");
    const res = await GET(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(401);
  });

  it("returns 400 for invalid platform", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    const { GET } = await import("@/app/api/platforms/[platform]/verify/route");
    const req = new Request("http://localhost/api/platforms/invalid/verify");
    const res = await GET(req, { params: Promise.resolve({ platform: "invalid" }) });
    expect(res.status).toBe(400);
  });

  it("returns 404 when no account found", async () => {
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

    const { GET } = await import("@/app/api/platforms/[platform]/verify/route");
    const req = new Request("http://localhost/api/platforms/resy/verify");
    const res = await GET(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(404);
  });

  it("decrypts and returns username on success", async () => {
    mockGetUser.mockResolvedValue({ data: { user: MOCK_USER } });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            single: vi.fn().mockResolvedValue({
              data: {
                id: "acct-1",
                platform: "resy",
                encrypted_username: "enc-user@test.com",
                encryption_iv: "iv-u|iv-p",
                encryption_tag: "tag-u|tag-p",
                is_connected: true,
                last_verified_at: null,
              },
              error: null,
            }),
          }),
        }),
      }),
    });

    const { GET } = await import("@/app/api/platforms/[platform]/verify/route");
    const req = new Request("http://localhost/api/platforms/resy/verify");
    const res = await GET(req, { params: Promise.resolve({ platform: "resy" }) });
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.verified).toBe(true);
    expect(json.platform).toBe("resy");
  });
});
