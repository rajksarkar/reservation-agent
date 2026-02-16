"use client";

import { useEffect, useState } from "react";
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
  InputAdornment,
  Stack,
  TextField,
  Typography,
  Alert,
} from "@mui/material";
import {
  Check,
  Close,
  Link as LinkIcon,
  LinkOff,
  Visibility,
  VisibilityOff,
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

export default function PlatformsPage() {
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [verifiedAccounts, setVerifiedAccounts] = useState<Record<string, VerifiedAccount>>({});
  const [connectDialog, setConnectDialog] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
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
      // Verify each connected account's stored credentials
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
          [platform]: { username: data.username, verified: true },
        }));
      } else {
        setVerifiedAccounts((prev) => ({
          ...prev,
          [platform]: { username: "", verified: false },
        }));
      }
    } catch {
      setVerifiedAccounts((prev) => ({
        ...prev,
        [platform]: { username: "", verified: false },
      }));
    }
  }

  async function handleConnect() {
    if (!connectDialog || !email || !password) return;
    setLoading(true);
    setError("");

    const platformName = platforms.find((p) => p.id === connectDialog)?.name || connectDialog;

    try {
      const res = await fetch(`/api/platforms/${connectDialog}/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to connect");

      // Verify credentials were stored correctly
      await verifyAccount(connectDialog);

      await loadAccounts();
      setSuccessMessage(`${platformName} connected successfully as ${email}`);
      setConnectDialog(null);
      setEmail("");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleDisconnect(accountId: string) {
    await supabase.from("platform_accounts").delete().eq("id", accountId);
    await loadAccounts();
  }

  function getAccount(platformId: string) {
    return accounts.find((a) => a.platform === platformId && a.is_connected);
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} sx={{ mb: 1 }}>
        Connected Platforms
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 4 }}>
        Connect your restaurant platform accounts to enable automated reservations.
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
                            Signed in as <strong>{verified.username}</strong>
                          </Typography>
                        </Stack>
                      ) : (
                        <Alert severity="error" variant="outlined" sx={{ py: 0.5 }}>
                          <Typography variant="body2">
                            Credentials could not be verified. Please reconnect.
                          </Typography>
                        </Alert>
                      )}
                    </Box>
                  )}
                  {account ? (
                    <Stack spacing={1}>
                      <Button
                        variant="outlined"
                        startIcon={<LinkIcon />}
                        onClick={() => setConnectDialog(platform.id)}
                        fullWidth
                      >
                        Update Credentials
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
                      onClick={() => setConnectDialog(platform.id)}
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

      {/* Connect Dialog */}
      <Dialog
        open={!!connectDialog}
        onClose={() => {
          setConnectDialog(null);
          setError("");
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            Connect {platforms.find((p) => p.id === connectDialog)?.name}
            <IconButton onClick={() => setConnectDialog(null)} size="small">
              <Close />
            </IconButton>
          </Stack>
        </DialogTitle>
        <DialogContent>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Your credentials are encrypted with AES-256-GCM before storage.
          </Typography>
          <TextField
            fullWidth
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            label="Password"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            slotProps={{
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      onClick={() => setShowPassword(!showPassword)}
                      edge="end"
                      size="small"
                    >
                      {showPassword ? <VisibilityOff /> : <Visibility />}
                    </IconButton>
                  </InputAdornment>
                ),
              },
            }}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 3 }}>
          <Button onClick={() => setConnectDialog(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleConnect}
            disabled={loading || !email || !password}
          >
            {loading ? "Verifying & Connecting..." : "Connect"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
