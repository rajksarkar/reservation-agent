"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
  LinearProgress,
  Stack,
  Typography,
  Alert,
} from "@mui/material";
import {
  Check,
  Close,
  Link as LinkIcon,
  LinkOff,
  OpenInNew,
} from "@mui/icons-material";
import { createClient } from "@/lib/supabase/client";

interface PlatformAccount {
  id: string;
  platform: string;
  is_connected: boolean;
  last_verified_at: string | null;
  created_at: string;
}

interface VerifiedAccount {
  username: string;
  authMethod: string;
  verified: boolean;
}

const platforms = [
  {
    id: "resy",
    name: "Resy",
    description: "Access restaurants like Carbone, Don Angie, Via Carota, and more.",
    color: "#e74c3c",
  },
  {
    id: "opentable",
    name: "OpenTable",
    description: "Book at Peter Luger, Le Bernardin, Daniel, and thousands more.",
    color: "#da3743",
  },
  {
    id: "tock",
    name: "Tock",
    description: "Reserve prepaid experiences at Eleven Madison Park, Atomix, and more.",
    color: "#1a1a2e",
  },
];

type AuthStep = "idle" | "launching" | "interactive" | "capturing" | "done" | "error";

export default function PlatformsPage() {
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [verifiedAccounts, setVerifiedAccounts] = useState<Record<string, VerifiedAccount>>({});
  const [connectPlatform, setConnectPlatform] = useState<string | null>(null);
  const [authStep, setAuthStep] = useState<AuthStep>("idle");
  const [authSessionId, setAuthSessionId] = useState<string | null>(null);
  const [liveViewUrl, setLiveViewUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const supabase = createClient();

  useEffect(() => {
    loadAccounts();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadAccounts() {
    const { data } = await supabase
      .from("platform_accounts")
      .select("id, platform, is_connected, last_verified_at, created_at");
    if (data) {
      setAccounts(data);
      for (const account of data.filter((a) => a.is_connected)) {
        verifyAccount(account.platform);
      }
    }
  }

  async function verifyAccount(platform: string) {
    try {
      const res = await fetch(`/api/platforms/${platform}/verify`);
      const data = await res.json();
      if (res.ok && data.verified) {
        setVerifiedAccounts((prev) => ({
          ...prev,
          [platform]: {
            username: data.username,
            authMethod: data.authMethod || "credentials",
            verified: true,
          },
        }));
      } else {
        setVerifiedAccounts((prev) => ({
          ...prev,
          [platform]: { username: "", authMethod: "", verified: false },
        }));
      }
    } catch {
      setVerifiedAccounts((prev) => ({
        ...prev,
        [platform]: { username: "", authMethod: "", verified: false },
      }));
    }
  }

  const startBrowserAuth = useCallback(async (platform: string) => {
    setConnectPlatform(platform);
    setAuthStep("launching");
    setError("");
    setLiveViewUrl(null);
    setAuthSessionId(null);

    try {
      const res = await fetch(`/api/platforms/${platform}/browser-auth/start`, {
        method: "POST",
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Failed to start browser session");
      }

      setAuthSessionId(data.authSessionId);
      setLiveViewUrl(data.liveViewUrl);
      setAuthStep("interactive");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to launch browser");
      setAuthStep("error");
    }
  }, []);

  async function completeBrowserAuth() {
    if (!authSessionId || !connectPlatform) return;
    setAuthStep("capturing");

    try {
      const res = await fetch(`/api/platforms/${connectPlatform}/browser-auth/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ authSessionId }),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Failed to capture session");
      }

      setAuthStep("done");
      const platformName = platforms.find((p) => p.id === connectPlatform)?.name || connectPlatform;
      setSuccessMessage(`${platformName} connected successfully via browser login!`);

      await loadAccounts();

      setTimeout(() => {
        closeDialog();
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save session");
      setAuthStep("error");
    }
  }

  async function closeDialog() {
    // Cancel the browser session if it's still active
    if (authSessionId && authStep !== "done" && authStep !== "idle") {
      fetch(`/api/platforms/${connectPlatform}/browser-auth/complete`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ authSessionId }),
      }).catch(() => {});
    }

    setConnectPlatform(null);
    setAuthStep("idle");
    setAuthSessionId(null);
    setLiveViewUrl(null);
    setError("");
  }

  async function handleDisconnect(accountId: string) {
    await supabase.from("platform_accounts").delete().eq("id", accountId);
    await loadAccounts();
  }

  function getAccount(platformId: string) {
    return accounts.find((a) => a.platform === platformId && a.is_connected);
  }

  const currentPlatform = platforms.find((p) => p.id === connectPlatform);

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} sx={{ mb: 1 }}>
        Connected Platforms
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 4 }}>
        Connect your restaurant platform accounts by logging in through a secure browser session.
      </Typography>

      {successMessage && (
        <Alert severity="success" sx={{ mb: 3 }} onClose={() => setSuccessMessage("")}>
          {successMessage}
        </Alert>
      )}

      <Grid container spacing={3}>
        {platforms.map((platform) => {
          const account = getAccount(platform.id);
          const verified = verifiedAccounts[platform.id];
          return (
            <Grid size={{ xs: 12, sm: 6, md: 4 }} key={platform.id}>
              <Card
                sx={{
                  height: "100%",
                  borderTop: `3px solid ${platform.color}`,
                }}
              >
                <CardContent sx={{ p: 3 }}>
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                    sx={{ mb: 2 }}
                  >
                    <Typography variant="h6" fontWeight={600}>
                      {platform.name}
                    </Typography>
                    {account ? (
                      <Chip
                        icon={<Check />}
                        label="Connected"
                        color="success"
                        size="small"
                      />
                    ) : (
                      <Chip label="Not connected" size="small" variant="outlined" />
                    )}
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    {platform.description}
                  </Typography>
                  {account && verified && (
                    <Box sx={{ mb: 2 }}>
                      {verified.verified ? (
                        <Stack direction="row" alignItems="center" spacing={0.5}>
                          <Check sx={{ fontSize: 16, color: "success.main" }} />
                          <Typography variant="body2" color="text.secondary">
                            {verified.authMethod === "browser"
                              ? "Authenticated via browser session"
                              : <>Signed in as <strong>{verified.username}</strong></>}
                          </Typography>
                        </Stack>
                      ) : (
                        <Alert severity="error" variant="outlined" sx={{ py: 0.5 }}>
                          <Typography variant="body2">
                            Session expired or invalid. Please reconnect.
                          </Typography>
                        </Alert>
                      )}
                    </Box>
                  )}
                  {account ? (
                    <Stack spacing={1}>
                      <Button
                        variant="outlined"
                        startIcon={<OpenInNew />}
                        onClick={() => startBrowserAuth(platform.id)}
                        fullWidth
                      >
                        Reconnect
                      </Button>
                      <Button
                        variant="outlined"
                        color="error"
                        startIcon={<LinkOff />}
                        onClick={() => handleDisconnect(account.id)}
                        fullWidth
                      >
                        Disconnect
                      </Button>
                    </Stack>
                  ) : (
                    <Button
                      variant="contained"
                      startIcon={<LinkIcon />}
                      onClick={() => startBrowserAuth(platform.id)}
                      fullWidth
                    >
                      Connect Account
                    </Button>
                  )}
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      {/* Browser Auth Dialog */}
      <Dialog
        open={!!connectPlatform}
        onClose={closeDialog}
        maxWidth="lg"
        fullWidth
        PaperProps={{
          sx: { height: "85vh", maxHeight: "85vh", display: "flex", flexDirection: "column" },
        }}
      >
        <DialogTitle sx={{ pb: 1 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Stack>
              <Typography variant="h6" fontWeight={600}>
                {authStep === "done"
                  ? `${currentPlatform?.name} Connected!`
                  : `Sign in to ${currentPlatform?.name}`}
              </Typography>
              {authStep === "interactive" && (
                <Typography variant="body2" color="text.secondary">
                  Log in below, then click &quot;I&apos;m Logged In&quot; when done
                </Typography>
              )}
            </Stack>
            <IconButton onClick={closeDialog} size="small">
              <Close />
            </IconButton>
          </Stack>
        </DialogTitle>

        <DialogContent
          sx={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            p: 0,
            overflow: "hidden",
          }}
        >
          {error && (
            <Alert severity="error" sx={{ mx: 3, mt: 2 }}>
              {error}
            </Alert>
          )}

          {authStep === "launching" && (
            <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 2 }}>
              <LinearProgress sx={{ width: 200 }} />
              <Typography color="text.secondary">
                Launching secure browser...
              </Typography>
            </Box>
          )}

          {authStep === "interactive" && liveViewUrl && (
            <Box sx={{ flex: 1, position: "relative" }}>
              <iframe
                src={`${liveViewUrl}&navbar=false`}
                style={{
                  width: "100%",
                  height: "100%",
                  border: "none",
                  display: "block",
                }}
                allow="clipboard-read; clipboard-write"
              />
            </Box>
          )}

          {authStep === "capturing" && (
            <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 2 }}>
              <LinearProgress sx={{ width: 200 }} />
              <Typography color="text.secondary">
                Capturing session...
              </Typography>
            </Box>
          )}

          {authStep === "done" && (
            <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, gap: 2 }}>
              <Check sx={{ fontSize: 64, color: "success.main" }} />
              <Typography variant="h6" color="success.main">
                Connected successfully!
              </Typography>
            </Box>
          )}
        </DialogContent>

        <DialogActions sx={{ px: 3, pb: 3, pt: 2, borderTop: "1px solid", borderColor: "divider" }}>
          <Button onClick={closeDialog} disabled={authStep === "capturing"}>
            Cancel
          </Button>
          {authStep === "interactive" && (
            <Button
              variant="contained"
              onClick={completeBrowserAuth}
              size="large"
            >
              I&apos;m Logged In
            </Button>
          )}
          {authStep === "error" && (
            <Button
              variant="contained"
              onClick={() => connectPlatform && startBrowserAuth(connectPlatform)}
            >
              Retry
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
