"use client";

import {
  Box,
  Button,
  Container,
  Typography,
  Grid,
  Card,
  CardContent,
  Stack,
} from "@mui/material";
import {
  Restaurant,
  Speed,
  Notifications,
  Security,
} from "@mui/icons-material";
import Link from "next/link";

const features = [
  {
    icon: <Speed sx={{ fontSize: 40, color: "primary.main" }} />,
    title: "Lightning-Fast Sniping",
    description:
      "Sub-second polling catches reservations the moment they drop. Beat the crowds to the most coveted tables.",
  },
  {
    icon: <Notifications sx={{ fontSize: 40, color: "secondary.main" }} />,
    title: "Cancellation Monitoring",
    description:
      "Continuous monitoring for cancellations at fully-booked restaurants. Get alerted and auto-book instantly.",
  },
  {
    icon: <Restaurant sx={{ fontSize: 40, color: "success.main" }} />,
    title: "Multi-Platform Support",
    description:
      "Works with Resy, OpenTable, and Tock. Connect your accounts and manage everything from one dashboard.",
  },
  {
    icon: <Security sx={{ fontSize: 40, color: "error.main" }} />,
    title: "Secure & Private",
    description:
      "AES-256 encrypted credentials. Your login details are never stored in plain text.",
  },
];

export default function LandingPage() {
  return (
    <Box sx={{ bgcolor: "background.default", minHeight: "100vh" }}>
      {/* Nav */}
      <Box
        sx={{
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          py: 2,
          px: 3,
        }}
      >
        <Container maxWidth="lg">
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Stack direction="row" alignItems="center" spacing={1}>
              <Restaurant sx={{ color: "primary.main" }} />
              <Typography variant="h6" fontWeight={700}>
                Reservation Jarvis
              </Typography>
            </Stack>
            <Stack direction="row" spacing={2}>
              <Button component={Link} href="/login" variant="text">
                Sign in
              </Button>
              <Button component={Link} href="/signup" variant="contained">
                Get Started
              </Button>
            </Stack>
          </Stack>
        </Container>
      </Box>

      {/* Hero */}
      <Container maxWidth="lg" sx={{ pt: { xs: 8, md: 14 }, pb: 10 }}>
        <Box sx={{ textAlign: "center", maxWidth: 720, mx: "auto" }}>
          <Typography
            variant="h2"
            fontWeight={800}
            sx={{
              fontSize: { xs: "2.2rem", md: "3.5rem" },
              lineHeight: 1.15,
              mb: 3,
              background: "linear-gradient(135deg, #6366f1, #f59e0b)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            Never miss a reservation again
          </Typography>
          <Typography
            variant="h6"
            color="text.secondary"
            sx={{ mb: 5, fontWeight: 400, lineHeight: 1.6 }}
          >
            Automatically snipe tables at NYC&apos;s hardest-to-book restaurants.
            Set your preferences and let Jarvis handle the rest.
          </Typography>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={2}
            justifyContent="center"
          >
            <Button
              component={Link}
              href="/signup"
              variant="contained"
              size="large"
              sx={{ px: 5, py: 1.5 }}
            >
              Start for Free
            </Button>
            <Button
              component={Link}
              href="/login"
              variant="outlined"
              size="large"
              sx={{ px: 5, py: 1.5, borderColor: "rgba(255,255,255,0.2)" }}
            >
              Sign in
            </Button>
          </Stack>
        </Box>
      </Container>

      {/* Features */}
      <Container maxWidth="lg" sx={{ pb: 14 }}>
        <Grid container spacing={3}>
          {features.map((feature) => (
            <Grid size={{ xs: 12, sm: 6, md: 3 }} key={feature.title}>
              <Card
                sx={{
                  height: "100%",
                  bgcolor: "rgba(255,255,255,0.02)",
                  "&:hover": {
                    bgcolor: "rgba(255,255,255,0.04)",
                    borderColor: "rgba(255,255,255,0.15)",
                  },
                  transition: "all 0.2s",
                }}
              >
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ mb: 2 }}>{feature.icon}</Box>
                  <Typography variant="h6" gutterBottom fontWeight={600}>
                    {feature.title}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {feature.description}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Container>
    </Box>
  );
}
