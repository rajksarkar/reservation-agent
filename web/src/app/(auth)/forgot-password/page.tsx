"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Box,
  Button,
  Container,
  TextField,
  Typography,
  Alert,
  Paper,
} from "@mui/material";
import { ArrowBack, Restaurant } from "@mui/icons-material";
import { createClient } from "@/lib/supabase/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const supabase = createClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });

    if (error) {
      setError(error.message);
    } else {
      setSuccess(true);
    }
    setLoading(false);
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        bgcolor: "background.default",
        px: 2,
      }}
    >
      <Container maxWidth="sm">
        <Paper
          elevation={0}
          sx={{
            p: { xs: 3, sm: 5 },
            border: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <Box sx={{ textAlign: "center", mb: 4 }}>
            <Restaurant sx={{ fontSize: 40, color: "primary.main", mb: 1 }} />
            <Typography variant="h4" fontWeight={700}>
              Reset password
            </Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              Enter your email and we&apos;ll send a reset link
            </Typography>
          </Box>

          {error && (
            <Alert severity="error" sx={{ mb: 3 }}>
              {error}
            </Alert>
          )}

          {success ? (
            <Alert severity="success" sx={{ mb: 3 }}>
              Check your email for a password reset link. It may take a minute to arrive.
            </Alert>
          ) : (
            <Box component="form" onSubmit={handleSubmit}>
              <TextField
                fullWidth
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                sx={{ mb: 3 }}
              />
              <Button
                type="submit"
                fullWidth
                variant="contained"
                size="large"
                disabled={loading}
                sx={{ py: 1.5 }}
              >
                {loading ? "Sending..." : "Send reset link"}
              </Button>
            </Box>
          )}

          <Box sx={{ textAlign: "center", mt: 3 }}>
            <Button
              component={Link}
              href="/login"
              startIcon={<ArrowBack />}
              size="small"
            >
              Back to sign in
            </Button>
          </Box>
        </Paper>
      </Container>
    </Box>
  );
}
