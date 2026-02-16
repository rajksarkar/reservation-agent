import Browserbase from "@browserbasehq/sdk";
import { chromium, type Browser, type BrowserContext } from "playwright-core";

const PLATFORM_LOGIN_URLS: Record<string, string> = {
  resy: "https://resy.com/login",
  opentable: "https://www.opentable.com/sign-in",
  tock: "https://www.exploretock.com/login",
};

const SESSION_TTL_MS = 10 * 60 * 1000; // 10 min max before auto-cleanup

interface ActiveSession {
  browser: Browser;
  context: BrowserContext;
  bbSessionId: string;
  platform: string;
  userId: string;
  createdAt: number;
}

// In-memory store for active browser auth sessions.
// Keyed by an opaque authSessionId we generate.
const activeSessions = new Map<string, ActiveSession>();

// Periodic cleanup of stale sessions
setInterval(() => {
  const now = Date.now();
  for (const [id, session] of activeSessions) {
    if (now - session.createdAt > SESSION_TTL_MS) {
      session.browser.close().catch(() => {});
      activeSessions.delete(id);
    }
  }
}, 60_000);

function generateId(): string {
  return crypto.randomUUID();
}

function getBrowserbase(): Browserbase {
  return new Browserbase({ apiKey: process.env.BROWSERBASE_API_KEY! });
}

/**
 * Start a browser auth session:
 * 1. Create BrowserBase cloud browser
 * 2. Connect Playwright via CDP
 * 3. Navigate to platform login page
 * 4. Get live view URL
 * 5. Store the connection in memory (keeps CDP alive)
 */
export async function startBrowserAuth(
  platform: string,
  userId: string
): Promise<{ authSessionId: string; liveViewUrl: string }> {
  const bb = getBrowserbase();

  const session = await bb.sessions.create({
    projectId: process.env.BROWSERBASE_PROJECT_ID!,
    browserSettings: {
      viewport: { width: 1280, height: 800 },
    },
  });

  const browser = await chromium.connectOverCDP(session.connectUrl);
  const context = browser.contexts()[0];
  const page = context.pages()[0] || (await context.newPage());

  const loginUrl = PLATFORM_LOGIN_URLS[platform] || PLATFORM_LOGIN_URLS.resy;
  await page.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: 30_000 });

  const debugInfo = await bb.sessions.debug(session.id);
  const liveViewUrl = debugInfo.debuggerFullscreenUrl;

  const authSessionId = generateId();
  activeSessions.set(authSessionId, {
    browser,
    context,
    bbSessionId: session.id,
    platform,
    userId,
    createdAt: Date.now(),
  });

  return { authSessionId, liveViewUrl };
}

/**
 * Complete a browser auth session:
 * 1. Extract cookies + localStorage from the still-connected browser
 * 2. Close the browser
 * 3. Return the storage state for Supabase storage
 */
export async function completeBrowserAuth(
  authSessionId: string
): Promise<{ storageState: object; platform: string; userId: string }> {
  const session = activeSessions.get(authSessionId);
  if (!session) {
    throw new Error("Browser auth session not found or expired");
  }

  try {
    const storageState = await session.context.storageState();
    return {
      storageState,
      platform: session.platform,
      userId: session.userId,
    };
  } finally {
    await session.browser.close().catch(() => {});
    activeSessions.delete(authSessionId);
  }
}

/**
 * Cancel/cleanup a browser auth session without capturing data.
 */
export async function cancelBrowserAuth(authSessionId: string): Promise<void> {
  const session = activeSessions.get(authSessionId);
  if (session) {
    await session.browser.close().catch(() => {});
    activeSessions.delete(authSessionId);
  }
}
