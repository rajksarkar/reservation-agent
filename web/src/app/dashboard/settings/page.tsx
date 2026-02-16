"use client";

import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Divider,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { createClient } from "@/lib/supabase/client";

interface Profile {
  full_name: string;
  email: string;
  phone: string;
  notification_email: boolean;
  notification_sms: boolean;
}

export default function SettingsPage() {
  const supabase = createClient();
  const [profile, setProfile] = useState<Profile>({
    full_name: "",
    email: "",
    phone: "",
    notification_email: true,
    notification_sms: false,
  });
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    async function load() {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return;

      const { data } = await supabase
        .from("profiles")
        .select("*")
        .eq("id", user.id)
        .single();

      if (data) {
        setProfile({
          full_name: data.full_name || "",
          email: data.email || "",
          phone: data.phone || "",
          notification_email: data.notification_email,
          notification_sms: data.notification_sms,
        });
      }
    }
    load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSave() {
    setSaving(true);
    setSuccess(false);

    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return;

    await supabase
      .from("profiles")
      .update({
        full_name: profile.full_name,
        phone: profile.phone,
        notification_email: profile.notification_email,
        notification_sms: profile.notification_sms,
      })
      .eq("id", user.id);

    setSaving(false);
    setSuccess(true);
    setTimeout(() => setSuccess(false), 3000);
  }

  return (
    <Box sx={{ maxWidth: 600, mx: "auto" }}>
      <Typography variant="h4" fontWeight={700} sx={{ mb: 4 }}>
        Settings
      </Typography>

      {success && (
        <Alert severity="success" sx={{ mb: 3 }}>
          Settings saved successfully.
        </Alert>
      )}

      <Card sx={{ mb: 3 }}>
        <CardContent sx={{ p: 4 }}>
          <Typography variant="h6" fontWeight={600} sx={{ mb: 3 }}>
            Profile
          </Typography>
          <Stack spacing={2.5}>
            <TextField
              fullWidth
              label="Full Name"
              value={profile.full_name}
              onChange={(e) =>
                setProfile({ ...profile, full_name: e.target.value })
              }
            />
            <TextField
              fullWidth
              label="Email"
              value={profile.email}
              disabled
              helperText="Email cannot be changed"
            />
            <TextField
              fullWidth
              label="Phone"
              value={profile.phone}
              onChange={(e) =>
                setProfile({ ...profile, phone: e.target.value })
              }
              placeholder="+1 (555) 000-0000"
            />
          </Stack>
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent sx={{ p: 4 }}>
          <Typography variant="h6" fontWeight={600} sx={{ mb: 3 }}>
            Notifications
          </Typography>
          <Stack spacing={1}>
            <FormControlLabel
              control={
                <Switch
                  checked={profile.notification_email}
                  onChange={(e) =>
                    setProfile({
                      ...profile,
                      notification_email: e.target.checked,
                    })
                  }
                />
              }
              label="Email notifications"
            />
            <Typography variant="body2" color="text.secondary" sx={{ ml: 6 }}>
              Get notified when a reservation is booked or requires attention.
            </Typography>
            <Divider sx={{ my: 1 }} />
            <FormControlLabel
              control={
                <Switch
                  checked={profile.notification_sms}
                  onChange={(e) =>
                    setProfile({
                      ...profile,
                      notification_sms: e.target.checked,
                    })
                  }
                />
              }
              label="SMS notifications"
            />
            <Typography variant="body2" color="text.secondary" sx={{ ml: 6 }}>
              Receive text messages for urgent booking updates.
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      <Button
        variant="contained"
        size="large"
        onClick={handleSave}
        disabled={saving}
        fullWidth
      >
        {saving ? "Saving..." : "Save Changes"}
      </Button>
    </Box>
  );
}
