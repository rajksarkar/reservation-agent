"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Alert,
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
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Paper,
} from "@mui/material";
import {
  ArrowBack,
  CheckCircle,
  DeleteOutline,
  Pause,
  PlayArrow,
  Cancel,
} from "@mui/icons-material";
import { createClient } from "@/lib/supabase/client";

interface ReservationDetail {
  id: string;
  party_size: number;
  target_dates: string[];
  preferred_times: string[];
  status: string;
  monitor_cancellations: boolean;
  release_snipe: boolean;
  release_time: string | null;
  release_days_ahead: number | null;
  booked_date: string | null;
  booked_time: string | null;
  confirmation_number: string | null;
  created_at: string;
  updated_at: string;
  restaurants: { name: string; platform: string; cuisine: string | null };
}

interface BookingAttempt {
  id: string;
  attempt_type: string;
  result: string;
  slot_time: string | null;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
}

const resultColors: Record<string, "success" | "warning" | "error" | "default"> = {
  success: "success",
  no_availability: "default",
  slot_taken: "warning",
  auth_failed: "error",
  error: "error",
};

export default function ReservationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const supabase = createClient();

  const [request, setRequest] = useState<ReservationDetail | null>(null);
  const [attempts, setAttempts] = useState<BookingAttempt[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  useEffect(() => {
    loadData();

    const channel = supabase
      .channel(`request-${id}`)
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "reservation_requests",
          filter: `id=eq.${id}`,
        },
        (payload) => {
          setRequest((prev) => (prev ? { ...prev, ...payload.new } : prev));
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadData() {
    const [reqRes, attRes] = await Promise.all([
      supabase
        .from("reservation_requests")
        .select("*, restaurants(name, platform, cuisine)")
        .eq("id", id)
        .single(),
      supabase
        .from("booking_attempts")
        .select("*")
        .eq("request_id", id)
        .order("created_at", { ascending: false })
        .limit(50),
    ]);
    if (reqRes.data) setRequest(reqRes.data);
    if (attRes.data) setAttempts(attRes.data);
    setLoading(false);
  }

  async function handleStatusChange(newStatus: string) {
    setActionLoading(true);
    await fetch(`/api/reservations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus }),
    });
    await loadData();
    setActionLoading(false);
  }

  async function handleDelete() {
    setActionLoading(true);
    const res = await fetch(`/api/reservations/${id}`, { method: "DELETE" });
    if (res.ok) {
      router.push("/dashboard");
    }
    setActionLoading(false);
    setShowDeleteDialog(false);
  }

  if (loading) {
    return (
      <Box>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rounded" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (!request) {
    return (
      <Box sx={{ textAlign: "center", mt: 8 }}>
        <Typography variant="h5" color="text.secondary">
          Request not found
        </Typography>
        <Button component={Link} href="/dashboard" sx={{ mt: 2 }}>
          Back to Dashboard
        </Button>
      </Box>
    );
  }

  return (
    <Box>
      <Button
        component={Link}
        href="/dashboard"
        startIcon={<ArrowBack />}
        sx={{ mb: 2 }}
      >
        Back
      </Button>

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h4" fontWeight={700}>
            {request.restaurants?.name}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
            <Chip label={request.restaurants?.platform} size="small" variant="outlined" />
            <Chip
              label={request.status}
              size="small"
              color={
                request.status === "booked"
                  ? "success"
                  : request.status === "active"
                  ? "info"
                  : request.status === "paused"
                  ? "warning"
                  : "default"
              }
            />
          </Stack>
        </Box>
        <Stack direction="row" spacing={1}>
          {request.status === "active" && (
            <Button
              variant="outlined"
              startIcon={<Pause />}
              onClick={() => handleStatusChange("paused")}
              disabled={actionLoading}
            >
              Pause
            </Button>
          )}
          {request.status === "paused" && (
            <Button
              variant="contained"
              startIcon={<PlayArrow />}
              onClick={() => handleStatusChange("active")}
              disabled={actionLoading}
            >
              Resume
            </Button>
          )}
          {(request.status === "active" || request.status === "paused") && (
            <Button
              variant="outlined"
              color="error"
              startIcon={<Cancel />}
              onClick={() => handleStatusChange("cancelled")}
              disabled={actionLoading}
            >
              Cancel
            </Button>
          )}
          <Button
            variant="outlined"
            color="error"
            startIcon={<DeleteOutline />}
            onClick={() => setShowDeleteDialog(true)}
            disabled={actionLoading}
          >
            Delete
          </Button>
        </Stack>
      </Stack>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteDialog} onClose={() => setShowDeleteDialog(false)}>
        <DialogTitle>Delete Reservation Request</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete the request for{" "}
            <strong>{request.restaurants?.name}</strong>? This will permanently
            remove it and all associated booking attempts.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowDeleteDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDelete}
            disabled={actionLoading}
          >
            {actionLoading ? "Deleting..." : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Booking confirmation */}
      {request.status === "booked" && (
        <Alert
          severity="success"
          icon={<CheckCircle />}
          sx={{ mb: 3 }}
        >
          <Typography fontWeight={600}>Reservation Booked!</Typography>
          <Typography variant="body2">
            {request.booked_date} at {request.booked_time}
            {request.confirmation_number && ` · Confirmation: ${request.confirmation_number}`}
          </Typography>
        </Alert>
      )}

      {/* Details */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
                Request Details
              </Typography>
              <Stack spacing={1.5}>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Party Size
                  </Typography>
                  <Typography>{request.party_size} guests</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Target Dates
                  </Typography>
                  <Stack direction="row" flexWrap="wrap" gap={0.5}>
                    {request.target_dates?.map((d) => (
                      <Chip key={d} label={d} size="small" />
                    ))}
                  </Stack>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Preferred Times
                  </Typography>
                  <Stack direction="row" flexWrap="wrap" gap={0.5}>
                    {request.preferred_times?.map((t) => (
                      <Chip key={t} label={t} size="small" variant="outlined" />
                    ))}
                  </Stack>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
                Monitoring Settings
              </Typography>
              <Stack spacing={1.5}>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Cancellation Monitoring
                  </Typography>
                  <Typography>
                    {request.monitor_cancellations ? "Enabled" : "Disabled"}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Release Snipe
                  </Typography>
                  <Typography>
                    {request.release_snipe
                      ? `Enabled · ${request.release_time}, ${request.release_days_ahead} days ahead`
                      : "Disabled"}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    Created
                  </Typography>
                  <Typography variant="body2">
                    {new Date(request.created_at).toLocaleString()}
                  </Typography>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Booking Attempts */}
      <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
        Booking Attempts ({attempts.length})
      </Typography>
      {attempts.length === 0 ? (
        <Card sx={{ p: 3, textAlign: "center" }}>
          <Typography color="text.secondary">
            No booking attempts yet. The worker will start checking once it picks up this request.
          </Typography>
        </Card>
      ) : (
        <TableContainer component={Paper} elevation={0}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Result</TableCell>
                <TableCell>Slot</TableCell>
                <TableCell>Duration</TableCell>
                <TableCell>Error</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {attempts.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    <Typography variant="caption">
                      {new Date(a.created_at).toLocaleString()}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={a.attempt_type} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={a.result}
                      size="small"
                      color={resultColors[a.result] || "default"}
                    />
                  </TableCell>
                  <TableCell>{a.slot_time || "—"}</TableCell>
                  <TableCell>
                    {a.duration_ms ? `${a.duration_ms}ms` : "—"}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption" color="error.main">
                      {a.error_message || ""}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
}
