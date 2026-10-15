"use client";

import { motion } from "framer-motion";
import { AlertCircle, Ban, Check, Circle, Loader2, Minus, RotateCcw, Square, Timer, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatTimestamp } from "@/lib/transcript-format";
import type { JobError, JobStatus, StageStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

function StageIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case "done":
      return <Check className="size-4 text-emerald-500" />;
    case "active":
      return <Loader2 className="size-4 animate-spin text-brand" />;
    case "error":
      return <X className="size-4 text-destructive" />;
    case "skipped":
      return <Minus className="size-4 text-muted-foreground/60" />;
    default:
      return <Circle className="size-3.5 text-muted-foreground/40" />;
  }
}

export function ProgressBar({ value }: { value: number | null }) {
  return (
    <div
      className="relative h-2 w-full overflow-hidden rounded-full bg-muted"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value == null ? undefined : Math.round(value * 100)}
      aria-label={value == null ? "In progress" : `${Math.round(value * 100)}%`}
    >
      {value == null ? (
        <div className="progress-indeterminate absolute inset-y-0 w-2/5 rounded-full bg-brand/80" />
      ) : (
        <div className="h-full rounded-full bg-brand transition-[width] duration-300" style={{ width: `${Math.max(2, value * 100)}%` }} />
      )}
    </div>
  );
}

const STOP_REASONS: Record<string, string> = {
  user_stopped: "Stopped by you",
  time_limit: "Session time limit reached",
  stream_ended: "The broadcast ended",
  source_error: "Live source became unavailable",
};

interface Props {
  job: JobStatus | null;
  requestError: JobError | null;
  starting: boolean;
  onCancel: () => void;
  onStop: () => void;
  onRetry: () => void;
  onDismiss: () => void;
}

export function ProcessingCard({ job, requestError, starting, onCancel, onStop, onRetry, onDismiss }: Props) {
  const error = job?.error ?? requestError;
  if (!job && !starting && !requestError) return null;

  if (!job) {
    return (
      <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="card-surface p-5" aria-live="polite">
        {starting ? (
          <div className="flex items-center gap-3 text-sm">
            <Loader2 className="size-4 animate-spin text-brand" /> Starting transcript job…
          </div>
        ) : (
          <ErrorBlock error={error!} onRetry={onRetry} onDismiss={onDismiss} />
        )}
      </motion.section>
    );
  }

  const isLive = job.kind === "live" && job.state === "live";
  const running = job.state === "queued" || job.state === "running" || job.state === "live";
  const live = job.live;
  const done = job.state === "completed";

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("card-surface overflow-hidden", isLive && "ring-1 ring-brand/40")}
      aria-live="polite"
      aria-label="Processing status"
    >
      <div className="flex flex-wrap items-center gap-3 border-b px-5 py-4">
        {isLive ? (
          <Badge className="gap-1.5 bg-brand font-bold tracking-wide text-white">
            <span className="size-2 animate-pulse rounded-full bg-white" /> LIVE
          </Badge>
        ) : done ? (
          <Check className="size-5 text-emerald-500" />
        ) : job.state === "failed" ? (
          <AlertCircle className="size-5 text-destructive" />
        ) : job.state === "cancelled" ? (
          <Ban className="size-5 text-muted-foreground" />
        ) : (
          <Loader2 className="size-5 animate-spin text-brand" />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">
            {done ? "Transcript ready" : job.state === "cancelled" ? "Cancelled" : job.state === "failed" ? "Transcript failed" : job.message}
          </p>
          {running && job.progress != null && (
            <p className="text-xs text-muted-foreground tabular-nums">{Math.round(job.progress * 100)}%</p>
          )}
        </div>
        {isLive && (
          <Button variant="destructive" onClick={onStop}>
            <Square className="fill-current" /> Stop &amp; keep transcript
          </Button>
        )}
        {running && !isLive && (
          <Button variant="outline" onClick={onCancel}>
            <X /> Cancel
          </Button>
        )}
      </div>

      {running && (
        <div className="space-y-3 px-5 pt-4">
          <ProgressBar value={isLive ? null : job.progress} />
          {live && (
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
              <span>
                <strong className="text-foreground tabular-nums">{job.segments_count}</strong> segments collected
              </span>
              <span>Source: {live.mode === "captions" ? "YouTube live captions" : "Live audio speech-to-text"}</span>
              {live.audio_seconds_processed != null && <span>Audio processed: {formatTimestamp(live.audio_seconds_processed)}</span>}
              {live.delay_seconds != null && (
                <span className={cn("inline-flex items-center gap-1", live.delay_seconds > 60 && "text-amber-600 dark:text-amber-400")}>
                  <Timer className="size-3.5" /> ≈{Math.round(live.delay_seconds)}s behind live
                </span>
              )}
              <span>Max session: {Math.round(live.max_session_seconds / 60)} min</span>
            </div>
          )}
          {!live && job.segments_count > 0 && (
            <p className="text-xs text-muted-foreground">
              <strong className="text-foreground tabular-nums">{job.segments_count}</strong> segments transcribed so far
            </p>
          )}
        </div>
      )}

      <ol
        className="grid gap-1.5 px-5 py-4 text-sm sm:grid-flow-col sm:grid-cols-2"
        style={{ gridTemplateRows: `repeat(${Math.ceil(job.stages.length / 2)}, auto)` }}
      >
        {job.stages.map((s, i) => (
          <li key={s.key} className={cn("flex items-center gap-2", s.status === "pending" && "text-muted-foreground", s.status === "skipped" && "text-muted-foreground/60 line-through")}>
            <StageIcon status={s.status} />
            <span className="tabular-nums text-muted-foreground">{i + 1}.</span>
            <span className={cn(s.status === "active" && "font-medium")}>{s.label}</span>
          </li>
        ))}
      </ol>

      {job.live?.stopped && job.live.stop_reason && (
        <p className="px-5 pb-4 text-xs text-muted-foreground">Live session ended: {STOP_REASONS[job.live.stop_reason] ?? job.live.stop_reason}</p>
      )}

      {error && (job.state === "failed" || requestError) && (
        <div className="border-t px-5 py-4">
          <ErrorBlock error={error} onRetry={onRetry} onDismiss={onDismiss} />
        </div>
      )}
    </motion.section>
  );
}

function ErrorBlock({ error, onRetry, onDismiss }: { error: JobError; onRetry: () => void; onDismiss: () => void }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
      <AlertCircle className="mt-0.5 size-5 shrink-0 text-destructive" />
      <div className="flex-1 space-y-1">
        <p className="font-medium text-destructive">{error.message}</p>
        {error.hint && <p className="text-sm text-muted-foreground">{error.hint}</p>}
        <p className="font-mono text-[11px] text-muted-foreground/70">code: {error.code}</p>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCcw /> Retry
        </Button>
        <Button variant="ghost" size="sm" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}
