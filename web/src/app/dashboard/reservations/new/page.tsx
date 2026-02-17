"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControlLabel,
  Grid,
  MenuItem,
  Stack,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
  Alert,
} from "@mui/material";
import { Schedule, Info, Warning, LinkOff } from "@mui/icons-material";
import { DateCalendar } from "@mui/x-date-pickers/DateCalendar";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { PickersDay, PickersDayProps } from "@mui/x-date-pickers/PickersDay";
import { format, isSameDay, isBefore, startOfDay, addDays, subDays } from "date-fns";
import { toZonedTime } from "date-fns-tz";
import { createClient } from "@/lib/supabase/client";

interface RestaurantOption {
  id: string;
  name: string;
  platform: string;
  cuisine: string | null;
  neighborhood: string | null;
  price_range: number | null;
  release_time: string | null;
  release_days_ahead: number | null;
  release_schedule_notes: string | null;
}

interface DateReleaseInfo {
  date: string; // YYYY-MM-DD
  releaseDate: Date; // when slots open (ET)
  released: boolean; // true if slots are already out
  releaseDateDisplay: string; // e.g. "Mon, Feb 22"
  releaseTimeDisplay: string; // e.g. "9:00 AM"
}

/**
 * For each target date, compute when its slots open based on the
 * restaurant's release schedule. Returns null when the restaurant
 * has no release schedule info.
 */
function analyzeDates(
  dates: string[],
  restaurant: RestaurantOption | null,
): DateReleaseInfo[] | null {
  if (!restaurant?.release_days_ahead) return null;

  const releaseTime = restaurant.release_time ?? "09:00:00";
  const [rh, rm] = releaseTime.split(":").map(Number);
  const daysAhead = restaurant.release_days_ahead;

  const nowET = toZonedTime(new Date(), "America/New_York");

  return dates.map((dateStr) => {
    const target = new Date(dateStr + "T00:00:00");
    const relDate = subDays(target, daysAhead);
    // Build the release datetime in ET
    const releaseDT = new Date(
      relDate.getFullYear(),
      relDate.getMonth(),
      relDate.getDate(),
      rh,
      rm,
      0,
    );
    const released = nowET >= releaseDT;

    const hour = rh === 0 ? 12 : rh > 12 ? rh - 12 : rh;
    const ampm = rh >= 12 ? "PM" : "AM";
    const timeDisplay =
      rh === 0 && rm === 0
        ? "12:00 AM (midnight)"
        : `${hour}:${String(rm).padStart(2, "0")} ${ampm}`;

    return {
      date: dateStr,
      releaseDate: releaseDT,
      released,
      releaseDateDisplay: format(releaseDT, "EEE, MMM d"),
      releaseTimeDisplay: timeDisplay,
    };
  });
}

const steps = ["Restaurant", "Date & Time", "Options", "Review"];

const timeSlots = [
  "17:00-18:00",
  "17:30-18:30",
  "18:00-19:00",
  "18:30-19:30",
  "19:00-20:00",
  "19:30-20:30",
  "20:00-21:00",
  "20:30-21:30",
  "21:00-22:00",
];

function formatReleaseTime(time: string | null): string {
  if (!time) return "";
  const [h, m] = time.split(":");
  const hour = parseInt(h);
  if (hour === 0 && m === "00") return "12:00 AM (midnight)";
  if (hour === 12) return "12:00 PM";
  if (hour > 12) return `${hour - 12}:${m} PM`;
  return `${hour}:${m} AM`;
}

export default function NewReservationPage() {
  const router = useRouter();
  const supabase = createClient();
  const [activeStep, setActiveStep] = useState(0);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Step 1: Restaurant
  const [restaurants, setRestaurants] = useState<RestaurantOption[]>([]);
  const [selectedRestaurant, setSelectedRestaurant] = useState<RestaurantOption | null>(null);

  // Step 2: Date & Time
  const [partySize, setPartySize] = useState(2);
  const [selectedDates, setSelectedDates] = useState<string[]>([]);
  const [selectedTimes, setSelectedTimes] = useState<string[]>([]);

  // Step 3: Options
  const [monitorCancellations, setMonitorCancellations] = useState(true);
  const [releaseSnipe, setReleaseSnipe] = useState(false);
  const [releaseTime, setReleaseTime] = useState("09:00");
  const [releaseDaysAhead, setReleaseDaysAhead] = useState(14);

  // Platform connection status
  const [connectedPlatforms, setConnectedPlatforms] = useState<string[]>([]);
  const [platformCheckDone, setPlatformCheckDone] = useState(false);

  useEffect(() => {
    async function loadRestaurants() {
      const { data } = await supabase
        .from("restaurants")
        .select("id, name, platform, cuisine, neighborhood, price_range, release_time, release_days_ahead, release_schedule_notes")
        .order("name");
      if (data) setRestaurants(data);
    }
    async function loadConnectedPlatforms() {
      const { data } = await supabase
        .from("platform_accounts")
        .select("platform")
        .eq("is_connected", true);
      if (data) setConnectedPlatforms(data.map((a) => a.platform));
      setPlatformCheckDone(true);
    }
    loadRestaurants();
    loadConnectedPlatforms();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const isPlatformConnected = selectedRestaurant
    ? connectedPlatforms.includes(selectedRestaurant.platform)
    : true;

  // Auto-populate release snipe settings when restaurant is selected
  function handleRestaurantSelect(restaurant: RestaurantOption | null) {
    setSelectedRestaurant(restaurant);
    if (restaurant) {
      if (restaurant.release_time) {
        setReleaseTime(restaurant.release_time.substring(0, 5));
        setReleaseSnipe(true);
      }
      if (restaurant.release_days_ahead) {
        setReleaseDaysAhead(restaurant.release_days_ahead);
      }
    }
  }

  // Auto-configure monitoring vs. snipe based on selected dates + release schedule
  useEffect(() => {
    const analysis = analyzeDates(selectedDates, selectedRestaurant);
    if (!analysis || analysis.length === 0) return;

    const hasReleased = analysis.some((a) => a.released);
    const hasUnreleased = analysis.some((a) => !a.released);

    // If all dates are unreleased → snipe only, no cancellation monitoring
    if (hasUnreleased && !hasReleased) {
      setReleaseSnipe(true);
      setMonitorCancellations(false);
    }
    // If some released, some not → both
    else if (hasUnreleased && hasReleased) {
      setReleaseSnipe(true);
      setMonitorCancellations(true);
    }
    // All released → cancellation monitoring, no snipe needed
    else if (hasReleased && !hasUnreleased) {
      setMonitorCancellations(true);
      // Don't auto-disable snipe in case user wants it
    }
  }, [selectedDates, selectedRestaurant]); // eslint-disable-line react-hooks/exhaustive-deps

  function removeDate(date: string) {
    setSelectedDates(selectedDates.filter((d) => d !== date));
  }

  function toggleTime(time: string) {
    setSelectedTimes((prev) =>
      prev.includes(time) ? prev.filter((t) => t !== time) : [...prev, time]
    );
  }

  function toggleDate(date: Date) {
    const iso = format(date, "yyyy-MM-dd");
    setSelectedDates((prev) =>
      prev.includes(iso) ? prev.filter((d) => d !== iso) : [...prev, iso].sort()
    );
  }

  function canAdvance() {
    switch (activeStep) {
      case 0:
        return !!selectedRestaurant && isPlatformConnected;
      case 1:
        return selectedDates.length > 0 && selectedTimes.length > 0 && partySize > 0;
      case 2:
        return true;
      default:
        return false;
    }
  }

  async function handleSubmit() {
    if (!selectedRestaurant) return;
    setSubmitting(true);
    setError("");

    try {
      const res = await fetch("/api/reservations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          restaurant_id: selectedRestaurant.id,
          party_size: partySize,
          target_dates: selectedDates,
          preferred_times: selectedTimes,
          monitor_cancellations: monitorCancellations,
          release_snipe: releaseSnipe,
          release_time: releaseSnipe ? releaseTime : null,
          release_days_ahead: releaseSnipe ? releaseDaysAhead : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to create request");
      router.push(`/dashboard/reservations/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
      setSubmitting(false);
    }
  }

  return (
    <Box sx={{ maxWidth: 720, mx: "auto" }}>
      <Typography variant="h4" fontWeight={700} sx={{ mb: 1 }}>
        New Reservation Request
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 4 }}>
        Set up your preferences and we&apos;ll automatically snipe a table for you.
      </Typography>

      <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <Card>
        <CardContent sx={{ p: 4 }}>
          {/* Step 1: Restaurant */}
          {activeStep === 0 && (
            <Box>
              <Typography variant="h6" fontWeight={600} sx={{ mb: 3 }}>
                Select a Restaurant
              </Typography>
              <Autocomplete
                options={restaurants}
                getOptionLabel={(r) => r.name}
                value={selectedRestaurant}
                onChange={(_, value) => handleRestaurantSelect(value)}
                renderOption={(props, option) => {
                  const { key, ...rest } = props;
                  return (
                    <li key={key} {...rest}>
                      <Stack sx={{ width: "100%" }}>
                        <Stack direction="row" justifyContent="space-between" alignItems="center">
                          <Typography fontWeight={500}>{option.name}</Typography>
                          {option.release_time && (
                            <Chip
                              icon={<Schedule sx={{ fontSize: 14 }} />}
                              label={`${formatReleaseTime(option.release_time)}${option.release_days_ahead ? ` · ${option.release_days_ahead}d` : ""}`}
                              size="small"
                              variant="outlined"
                              color="primary"
                              sx={{ ml: 1, fontSize: "0.7rem", height: 22 }}
                            />
                          )}
                        </Stack>
                        <Typography variant="caption" color="text.secondary">
                          {option.platform} &middot; {option.cuisine || "Various"} &middot;{" "}
                          {option.neighborhood || "NYC"}
                          {option.price_range && ` · ${"$".repeat(option.price_range)}`}
                        </Typography>
                      </Stack>
                    </li>
                  );
                }}
                renderInput={(params) => (
                  <TextField {...params} label="Search restaurants" placeholder="Type to search..." />
                )}
              />
              {selectedRestaurant && (
                <>
                  {platformCheckDone && !isPlatformConnected && (
                    <Alert
                      severity="warning"
                      icon={<LinkOff />}
                      sx={{ mt: 3 }}
                      action={
                        <Button
                          color="warning"
                          size="small"
                          href="/dashboard/platforms"
                          sx={{ whiteSpace: "nowrap" }}
                        >
                          Connect Now
                        </Button>
                      }
                    >
                      Your <strong>{selectedRestaurant.platform}</strong> account is not connected.
                      You must connect it before creating a reservation request.
                    </Alert>
                  )}
                  <Card sx={{ mt: 2, bgcolor: "rgba(99,102,241,0.06)" }}>
                    <CardContent>
                      <Stack direction="row" justifyContent="space-between" alignItems="center">
                        <Typography fontWeight={600}>{selectedRestaurant.name}</Typography>
                        <Chip
                          label={isPlatformConnected ? "Connected" : "Not connected"}
                          size="small"
                          color={isPlatformConnected ? "success" : "default"}
                          variant={isPlatformConnected ? "filled" : "outlined"}
                        />
                      </Stack>
                      <Typography variant="body2" color="text.secondary">
                        {selectedRestaurant.platform} &middot;{" "}
                        {selectedRestaurant.cuisine || "Various"} &middot;{" "}
                        {selectedRestaurant.neighborhood || "NYC"}
                      </Typography>
                      {(selectedRestaurant.release_time || selectedRestaurant.release_schedule_notes) && (
                        <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mt: 1.5 }}>
                          <Info sx={{ fontSize: 16, color: "primary.main" }} />
                          <Typography variant="body2" color="primary.main">
                            Reservations drop at{" "}
                            <strong>{formatReleaseTime(selectedRestaurant.release_time)}</strong>
                            {selectedRestaurant.release_days_ahead
                              ? `, ${selectedRestaurant.release_days_ahead} days ahead`
                              : ""}
                            {selectedRestaurant.release_schedule_notes
                              ? ` (${selectedRestaurant.release_schedule_notes})`
                              : ""}
                          </Typography>
                        </Stack>
                      )}
                    </CardContent>
                  </Card>
                </>
              )}
            </Box>
          )}

          {/* Step 2: Date & Time */}
          {activeStep === 1 && (
            <Box>
              <Typography variant="h6" fontWeight={600} sx={{ mb: 3 }}>
                Party Size & Preferred Dates/Times
              </Typography>
              <TextField
                select
                label="Party Size"
                value={partySize}
                onChange={(e) => setPartySize(Number(e.target.value))}
                sx={{ mb: 3, minWidth: 120 }}
              >
                {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
                  <MenuItem key={n} value={n}>
                    {n} {n === 1 ? "guest" : "guests"}
                  </MenuItem>
                ))}
              </TextField>

              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Target Dates
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Click dates on the calendar to select or deselect them.
              </Typography>
              <LocalizationProvider dateAdapter={AdapterDateFns}>
                <DateCalendar
                  disablePast
                  onChange={(date) => date && toggleDate(date)}
                  sx={{
                    width: "100%",
                    maxWidth: 360,
                    "& .MuiPickersDay-root": { borderRadius: 1 },
                  }}
                  slots={{
                    day: (dayProps: PickersDayProps) => {
                      const isSelected = selectedDates.some((d) =>
                        isSameDay(new Date(d + "T00:00:00"), dayProps.day)
                      );
                      return (
                        <PickersDay
                          {...dayProps}
                          selected={isSelected}
                          disableMargin
                          sx={{
                            ...(isSelected && {
                              bgcolor: "primary.main",
                              color: "primary.contrastText",
                              fontWeight: 700,
                              "&:hover": { bgcolor: "primary.dark" },
                              "&:focus": { bgcolor: "primary.main" },
                            }),
                          }}
                        />
                      );
                    },
                  }}
                />
              </LocalizationProvider>
              <Stack direction="row" flexWrap="wrap" gap={1} sx={{ mb: 2 }}>
                {selectedDates.map((date) => (
                  <Chip
                    key={date}
                    label={format(new Date(date + "T00:00:00"), "EEE, MMM d")}
                    onDelete={() => removeDate(date)}
                  />
                ))}
                {selectedDates.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    No dates selected
                  </Typography>
                )}
              </Stack>

              {/* Release date analysis */}
              {(() => {
                const analysis = analyzeDates(selectedDates, selectedRestaurant);
                if (!analysis || analysis.length === 0) return null;
                const released = analysis.filter((a) => a.released);
                const unreleased = analysis.filter((a) => !a.released);

                // Find the first date whose slots haven't been released yet
                const firstUnreleasedTarget = unreleased.length
                  ? format(new Date(unreleased[0].date + "T00:00:00"), "MMM d")
                  : null;

                return (
                  <Card sx={{ mb: 3, bgcolor: "rgba(99,102,241,0.05)", border: "1px solid", borderColor: "divider" }}>
                    <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
                      <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 1 }}>
                        <Schedule sx={{ fontSize: 18, color: "primary.main" }} />
                        <Typography variant="subtitle2" color="primary.main">
                          Slot Release Schedule
                        </Typography>
                      </Stack>
                      {released.length > 0 && (
                        <Typography variant="body2" sx={{ mb: 0.5 }}>
                          <strong>Already released:</strong>{" "}
                          {released.map((r) => format(new Date(r.date + "T00:00:00"), "MMM d")).join(", ")}
                          {" — cancellation monitoring will be active."}
                        </Typography>
                      )}
                      {unreleased.length > 0 && (
                        <Typography variant="body2" color="warning.main" sx={{ fontWeight: 500 }}>
                          {firstUnreleasedTarget} onwards: slots not yet released.
                          {unreleased.length === 1
                            ? ` Opens ${unreleased[0].releaseDateDisplay} at ${unreleased[0].releaseTimeDisplay} ET.`
                            : ` Next opens ${unreleased[0].releaseDateDisplay} at ${unreleased[0].releaseTimeDisplay} ET.`}
                          {" Snipe will trigger automatically."}
                        </Typography>
                      )}
                      {unreleased.length > 1 && (
                        <Box sx={{ mt: 0.5, ml: 1 }}>
                          {unreleased.map((u) => (
                            <Typography key={u.date} variant="caption" color="text.secondary" display="block">
                              {format(new Date(u.date + "T00:00:00"), "EEE, MMM d")} — opens {u.releaseDateDisplay} at {u.releaseTimeDisplay} ET
                            </Typography>
                          ))}
                        </Box>
                      )}
                    </CardContent>
                  </Card>
                );
              })()}

              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Preferred Time Windows
              </Typography>
              <Grid container spacing={1}>
                {timeSlots.map((time) => (
                  <Grid key={time}>
                    <Chip
                      label={time}
                      onClick={() => toggleTime(time)}
                      color={selectedTimes.includes(time) ? "primary" : "default"}
                      variant={selectedTimes.includes(time) ? "filled" : "outlined"}
                      sx={{ cursor: "pointer" }}
                    />
                  </Grid>
                ))}
              </Grid>
            </Box>
          )}

          {/* Step 3: Options */}
          {activeStep === 2 && (
            <Box>
              <Typography variant="h6" fontWeight={600} sx={{ mb: 3 }}>
                Monitoring Options
              </Typography>

              {/* Auto-config banner based on date analysis */}
              {(() => {
                const analysis = analyzeDates(selectedDates, selectedRestaurant);
                if (!analysis || analysis.length === 0) return null;
                const hasReleased = analysis.some((a) => a.released);
                const hasUnreleased = analysis.some((a) => !a.released);

                if (hasUnreleased && !hasReleased) {
                  return (
                    <Alert severity="info" sx={{ mb: 3 }} icon={<Schedule />}>
                      All selected dates have slots that haven&apos;t been released yet.
                      Cancellation monitoring is off — a snipe will trigger when slots open.
                    </Alert>
                  );
                }
                if (hasUnreleased && hasReleased) {
                  return (
                    <Alert severity="info" sx={{ mb: 3 }} icon={<Schedule />}>
                      Some dates are already released (cancellation monitoring active),
                      while others will be sniped when their slots open.
                    </Alert>
                  );
                }
                return null;
              })()}

              <FormControlLabel
                control={
                  <Checkbox
                    checked={monitorCancellations}
                    onChange={(e) => setMonitorCancellations(e.target.checked)}
                  />
                }
                label="Monitor for cancellations"
              />
              <Typography variant="body2" color="text.secondary" sx={{ ml: 4, mb: 3 }}>
                Continuously check for newly available slots from cancellations.
              </Typography>

              <FormControlLabel
                control={
                  <Checkbox
                    checked={releaseSnipe}
                    onChange={(e) => setReleaseSnipe(e.target.checked)}
                  />
                }
                label="Enable release snipe"
              />
              <Typography variant="body2" color="text.secondary" sx={{ ml: 4, mb: 2 }}>
                Rapidly poll at the exact time new reservations are released.
              </Typography>

              {releaseSnipe && (
                <Box sx={{ ml: 4, mt: 1 }}>
                  {selectedRestaurant?.release_time && (
                    <Alert severity="info" sx={{ mb: 2 }} icon={<Schedule />}>
                      Auto-filled from restaurant data: releases at{" "}
                      <strong>{formatReleaseTime(selectedRestaurant.release_time)}</strong>
                      {selectedRestaurant.release_days_ahead
                        ? `, ${selectedRestaurant.release_days_ahead} days ahead`
                        : ""}
                      {selectedRestaurant.release_schedule_notes
                        ? ` (${selectedRestaurant.release_schedule_notes})`
                        : ""}
                    </Alert>
                  )}
                  <Stack direction="row" spacing={2}>
                    <TextField
                      label="Release time"
                      type="time"
                      value={releaseTime}
                      onChange={(e) => setReleaseTime(e.target.value)}
                      size="small"
                      slotProps={{ inputLabel: { shrink: true } }}
                    />
                    <TextField
                      label="Days ahead"
                      type="number"
                      value={releaseDaysAhead}
                      onChange={(e) => setReleaseDaysAhead(Number(e.target.value))}
                      size="small"
                      slotProps={{
                        htmlInput: { min: 1, max: 60 },
                      }}
                      sx={{ width: 120 }}
                    />
                  </Stack>
                </Box>
              )}
            </Box>
          )}

          {/* Step 4: Review */}
          {activeStep === 3 && (
            <Box>
              <Typography variant="h6" fontWeight={600} sx={{ mb: 3 }}>
                Review Your Request
              </Typography>
              <Stack spacing={2}>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary">
                    Restaurant
                  </Typography>
                  <Typography fontWeight={500}>
                    {selectedRestaurant?.name} ({selectedRestaurant?.platform})
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary">
                    Party Size
                  </Typography>
                  <Typography>{partySize} guests</Typography>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary">
                    Target Dates
                  </Typography>
                  <Stack direction="row" flexWrap="wrap" gap={1}>
                    {selectedDates.map((d) => (
                      <Chip key={d} label={format(new Date(d + "T00:00:00"), "EEE, MMM d")} size="small" />
                    ))}
                  </Stack>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary">
                    Preferred Times
                  </Typography>
                  <Stack direction="row" flexWrap="wrap" gap={1}>
                    {selectedTimes.map((t) => (
                      <Chip key={t} label={t} size="small" />
                    ))}
                  </Stack>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary">
                    Strategy
                  </Typography>
                  {(() => {
                    const analysis = analyzeDates(selectedDates, selectedRestaurant);
                    if (analysis && analysis.length > 0) {
                      const released = analysis.filter((a) => a.released);
                      const unreleased = analysis.filter((a) => !a.released);
                      return (
                        <Stack spacing={0.5}>
                          {released.length > 0 && (
                            <Typography variant="body2">
                              Cancellation monitoring for{" "}
                              {released.map((r) => format(new Date(r.date + "T00:00:00"), "MMM d")).join(", ")}
                              {" (already released)"}
                            </Typography>
                          )}
                          {unreleased.length > 0 && (
                            <Typography variant="body2" color="primary.main">
                              Snipe for{" "}
                              {unreleased.map((u) =>
                                `${format(new Date(u.date + "T00:00:00"), "MMM d")} (opens ${u.releaseDateDisplay} at ${u.releaseTimeDisplay})`
                              ).join(", ")}
                            </Typography>
                          )}
                        </Stack>
                      );
                    }
                    return (
                      <Typography variant="body2">
                        {monitorCancellations ? "Cancellation monitoring enabled" : "No cancellation monitoring"}
                        {releaseSnipe && ` · Release snipe at ${formatReleaseTime(releaseTime)}, ${releaseDaysAhead} days ahead`}
                      </Typography>
                    );
                  })()}
                </Box>
              </Stack>
            </Box>
          )}
        </CardContent>
      </Card>

      {/* Navigation */}
      <Stack direction="row" justifyContent="space-between" sx={{ mt: 3 }}>
        <Button
          disabled={activeStep === 0}
          onClick={() => setActiveStep((s) => s - 1)}
        >
          Back
        </Button>
        {activeStep < steps.length - 1 ? (
          <Button
            variant="contained"
            onClick={() => setActiveStep((s) => s + 1)}
            disabled={!canAdvance()}
          >
            Next
          </Button>
        ) : (
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={submitting}
          >
            {submitting ? "Creating..." : "Create Request"}
          </Button>
        )}
      </Stack>
    </Box>
  );
}
