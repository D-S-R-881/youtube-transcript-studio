"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CalendarClock, Captions, CaptionsOff, Clock, ExternalLink, Radio, User } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDuration } from "@/lib/transcript-format";
import type { VideoInfo, VideoType } from "@/lib/types";

export const VIDEO_TYPE_LABEL: Record<VideoType, string> = {
  regular: "Video",
  short: "Short",
  live: "Live now",
  live_replay: "Live replay",
  upcoming: "Upcoming live",
  unavailable: "Unavailable",
  unknown: "Video",
};

function captionSummary(info: VideoInfo): { ok: boolean; text: string } {
  const tracks = info.caption_tracks ?? [];
  if (tracks.length) {
    const manual = tracks.filter((t) => !t.is_generated).length;
    const auto = tracks.length - manual;
    const parts = [manual && `${manual} manual`, auto && `${auto} auto-generated`].filter(Boolean);
    return { ok: true, text: `Captions: ${parts.join(", ")}` };
  }
  if (info.captions_status === "rate_limited") return { ok: false, text: "Caption check rate limited" };
  if (info.captions_status && info.captions_status !== "available") return { ok: false, text: "No captions found" };
  return { ok: false, text: "Captions unknown" };
}

export function VideoPreviewCard({ info, loading, error }: { info: VideoInfo | null; loading: boolean; error: string | null }) {
  return (
    <AnimatePresence mode="wait">
      {loading ? (
        <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="card-surface flex gap-4 p-4">
          <Skeleton className="aspect-video w-40 shrink-0 rounded-xl sm:w-56" />
          <div className="flex-1 space-y-2 py-1">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        </motion.div>
      ) : error ? (
        <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="card-surface flex items-center gap-3 p-4 text-sm text-muted-foreground">
          <AlertTriangle className="size-5 shrink-0 text-amber-500" /> {error}
        </motion.div>
      ) : info ? (
        <motion.article
          key={info.video_id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className="card-surface flex flex-col gap-4 p-4 sm:flex-row"
          aria-label="Video preview"
        >
          <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-xl bg-muted sm:w-56">
            {info.thumbnail_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={info.thumbnail_url} alt="" className="size-full object-cover" loading="lazy" referrerPolicy="no-referrer" />
            )}
            {info.video_type === "live" && (
              <span className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-md bg-brand px-1.5 py-0.5 text-[11px] font-bold tracking-wide text-white">
                <span className="size-1.5 animate-pulse rounded-full bg-white" /> LIVE
              </span>
            )}
            {formatDuration(info.duration_seconds) && (
              <span className="absolute right-2 bottom-2 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[11px] text-white">
                {formatDuration(info.duration_seconds)}
              </span>
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <h2 className="line-clamp-2 text-base font-semibold leading-snug">
              {info.title ?? "Untitled video"}
              <a href={info.video_url} target="_blank" rel="noopener noreferrer" className="ml-1.5 inline-flex align-middle text-muted-foreground hover:text-foreground" aria-label="Open on YouTube">
                <ExternalLink className="size-3.5" />
              </a>
            </h2>
            {info.channel && (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <User className="size-3.5" /> {info.channel}
              </p>
            )}
            <div className="flex flex-wrap gap-1.5">
              <Badge variant={info.video_type === "live" ? "default" : "secondary"}>
                {info.video_type === "live" ? <Radio /> : null}
                {VIDEO_TYPE_LABEL[info.video_type]}
              </Badge>
              {formatDuration(info.duration_seconds) && (
                <Badge variant="outline">
                  <Clock /> {formatDuration(info.duration_seconds)}
                </Badge>
              )}
              {info.video_type === "upcoming" && info.scheduled_start && (
                <Badge variant="outline">
                  <CalendarClock /> {new Date(info.scheduled_start).toLocaleString()}
                </Badge>
              )}
              {info.availability === "available" || info.availability === "unknown" ? (
                (() => {
                  const c = captionSummary(info);
                  return (
                    <Badge variant="outline" className={c.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}>
                      {c.ok ? <Captions /> : <CaptionsOff />} {c.text}
                    </Badge>
                  );
                })()
              ) : null}
            </div>
            {info.availability !== "available" && info.availability_reason && (
              <p className="flex items-start gap-1.5 text-sm text-amber-600 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {info.availability_reason}
              </p>
            )}
            {info.video_type === "upcoming" && (
              <p className="text-sm text-muted-foreground">This livestream hasn&apos;t started yet. Come back once it&apos;s live.</p>
            )}
            {info.video_type === "live" && (
              <p className="text-sm text-muted-foreground">
                Active broadcast — live transcription works only if live captions or permitted audio are available.
              </p>
            )}
          </div>
        </motion.article>
      ) : null}
    </AnimatePresence>
  );
}
