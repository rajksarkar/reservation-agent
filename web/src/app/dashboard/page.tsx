"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  Paper,
  Skeleton,
} from "@mui/material";
import {
  Add,
  Restaurant,
  CheckCircle,
  Schedule,
  TrendingUp,
  Visibility,
  DeleteOutline,
} from "@mui/icons-material";
import { createClient } from "@/lib/supabase/client";

interface ReservationRequest {
  id: string;
  party_size: number;
  target_dates: string[];
  preferred_times: string[];
  status: string;
  created_at: string;
  restaurants: { name: string; platform: string };
}

interface ActivityItem {
  id: string;
  event_type: string;
  title: string;
  description: string | null;
  created_at: string;
}

const statusColors: Record<string, "success" | "warning" | "info" | "error" | "default"> = {
  active: "info",
  paused: "warning",
  booked: "success",
  cancelled: "error",
  expired: "default",
};

export default function DashboardPage() {
  const [requests, setRequests] = useState<ReservationRequest[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<ReservationRequest | null>(null);
  const [deleting, setDeleting] = useState(false);
  const supabase = createClient();

  useEffect(() => {
    async function load() {
      const [reqRes, actRes] = await Promise.all([
        supabase
          .from("reservation_requests")
          .select("*, restaurants(name, platform)")
          .order("created_at", { ascending: false })
          .limit(10),
        supabase
          .from("activity_log")
          .select("*")
          .order("created_at", { ascending: false })
          .limit(5),
      ]);
      if (reqRes.data) setRequests(reqRes.data);
      if (actRes.data) setActivity(actRes.data);
      setLoading(false);
    }
    load();

    // Realtime subscription for request status updates
    const channel = supabase
      .channel("request-updates")
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "reservation_requests" },
        (payload) => {
          setRequests((prev) =>
            prev.map((r) => (r.id === payload.new.id ? { ...r, ...payload.new } : r))
          );
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const res = await fetch(`/api/reservations/${deleteTarget.id}`, { method: "DELETE" });
      if (res.ok) {
        setRequests((prev) => prev.filter((r) => r.id !== deleteTarget.id));
      }
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  }

  const stats = {
    active: requests.filter((r) => r.status === "active").length,
    booked: requests.filter((r) => r.status === "booked").length,
    total: requests.length,
  };

  if (loading) {
    return (
      <Box>
        <Skeleton variant="text" width={200} height={40} />
        <Grid container spacing={3} sx={{ mt: 1 }}>
          {[1, 2, 3].map((i) => (
            <Grid size={{ xs: 12, sm: 4 }} key={i}>
              <Skeleton variant="rounded" height={120} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  return (
    <Box>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Typography variant="h4" fontWeight={700}>
          Dashboard
        </Typography>
        <Button
          component={Link}
          href="/dashboard/reservations/new"
          variant="contained"
          startIcon={<Add />}
        >
          New Request
        </Button>
      </Stack>

      {/* Stats Cards */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Card>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Active Requests
                  </Typography>
                  <Typography variant="h3" fontWeight={700}>
                    {stats.active}
                  </Typography>
                </Box>
                <Schedule sx={{ fontSize: 40, color: "info.main", opacity: 0.7 }} />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Card>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Booked
                  </Typography>
                  <Typography variant="h3" fontWeight={700} color="success.main">
                    {stats.booked}
                  </Typography>
                </Box>
                <CheckCircle sx={{ fontSize: 40, color: "success.main", opacity: 0.7 }} />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Card>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Box>
                  <Typography variant="body2" color="text.secondary">
                    Total Requests
                  </Typography>
                  <Typography variant="h3" fontWeight={700}>
                    {stats.total}
                  </Typography>
                </Box>
                <TrendingUp sx={{ fontSize: 40, color: "primary.main", opacity: 0.7 }} />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Active Requests Table */}
      <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
        Recent Requests
      </Typography>
      {requests.length === 0 ? (
        <Card sx={{ p: 4, textAlign: "center" }}>
          <Restaurant sx={{ fontSize: 48, color: "text.secondary", mb: 2 }} />
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No reservation requests yet
          </Typography>
          <Button
            component={Link}
            href="/dashboard/reservations/new"
            variant="contained"
            startIcon={<Add />}
            sx={{ mt: 1 }}
          >
            Create your first request
          </Button>
        </Card>
      ) : (
        <TableContainer component={Paper} elevation={0}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Restaurant</TableCell>
                <TableCell>Platform</TableCell>
                <TableCell>Party Size</TableCell>
                <TableCell>Dates</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {requests.map((req) => (
                <TableRow key={req.id} hover>
                  <TableCell>
                    <Typography fontWeight={500}>
                      {req.restaurants?.name || "Unknown"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={req.restaurants?.platform || "—"}
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>{req.party_size}</TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">
                      {req.target_dates?.length || 0} date(s)
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={req.status}
                      size="small"
                      color={statusColors[req.status] || "default"}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" justifyContent="flex-end" spacing={0.5}>
                      <Tooltip title="View details">
                        <IconButton
                          component={Link}
                          href={`/dashboard/reservations/${req.id}`}
                          size="small"
                        >
                          <Visibility fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => setDeleteTarget(req)}
                        >
                          <DeleteOutline fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete Reservation Request</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete the request for{" "}
            <strong>{deleteTarget?.restaurants?.name}</strong>? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? "Deleting..." : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Activity Feed */}
      {activity.length > 0 && (
        <Box sx={{ mt: 4 }}>
          <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
            Recent Activity
          </Typography>
          <Stack spacing={1}>
            {activity.map((item) => (
              <Card key={item.id} sx={{ bgcolor: "rgba(255,255,255,0.02)" }}>
                <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Box>
                      <Typography variant="body2" fontWeight={500}>
                        {item.title}
                      </Typography>
                      {item.description && (
                        <Typography variant="caption" color="text.secondary">
                          {item.description}
                        </Typography>
                      )}
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(item.created_at).toLocaleString()}
                    </Typography>
                  </Stack>
                </CardContent>
              </Card>
            ))}
          </Stack>
        </Box>
      )}
    </Box>
  );
}
