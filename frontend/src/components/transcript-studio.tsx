"use client";

import { motion } from "framer-motion";
import { Braces, Captions, FileText, Radio } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConverterSection } from "@/components/converter-section";
import { ProcessingCard } from "@/components/processing-card";
import { ResultsSection } from "@/components/results-section";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { UrlInputCard } from "@/components/url-input-card";
import { VideoPreviewCard } from "@/components/video-preview-card";
import { liveResultFrom, useTranscriptJob } from "@/hooks/use-transcript-job";
import { api, ApiError } from "@/lib/api";
import type { Capabilities, TranscriptSettings, VideoInfo } from "@/lib/types";
import { parseYouTubeUrl } from "@/lib/youtube";

const DEFAULT_SETTINGS: TranscriptSettings = {
  language: "auto",
  includeTimestamps: true,
  source: "auto",
  liveMode: "continuous",
  liveMaxMinutes: 30,
};

function useVideoInfo(url: string, videoId: string | null) {
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInfo(null);
    setError(null);
    if (!videoId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        setInfo(await api.videoInfo(url, ctrl.signal));
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setError(e instanceof ApiError ? e.message : "Could not load video details.");
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, 350);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
    // Only refetch when the video changes, not on every tracking-param edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  return { info, loading, error };
}

export function TranscriptStudio() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [url, setUrl] = useState("");
  const [settings, setSettings] = useState<TranscriptSettings>(DEFAULT_SETTINGS);
  const lastAction = useRef<(() => void) | null>(null);
  const job = useTranscriptJob();

  useEffect(() => {
    // Retry so a backend waking from an idle shutdown still reports its capabilities.
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = (attempt: number) => {
      api.capabilities().then(
        (c) => !cancelled && setCapabilities(c),
        () => {
          if (!cancelled && attempt < 4) timer = setTimeout(() => load(attempt + 1), 5000 * (attempt + 1));
        },
      );
    };
    load(0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  const parsed = useMemo(() => (url.trim() ? parseYouTubeUrl(url) : null), [url]);
  const videoId = parsed?.ok ? parsed.value.videoId : null;
  const { info, loading, error } = useVideoInfo(url.trim(), videoId);

  useEffect(() => {
    setSettings((s) => ({ ...s, language: "auto" }));
  }, [videoId]);

  const busy = job.starting || Boolean(job.job && ["queued", "running", "live"].includes(job.job.state));

  const generate = useCallback(() => {
    if (!parsed?.ok) return;
    const action = () => void job.start(url.trim(), settings);
    lastAction.current = action;
    action();
  }, [parsed, url, settings, job]);

  const upload = useCallback(
    (file: File) => {
      const action = () => void job.startUpload(file, settings.language, settings.includeTimestamps);
      lastAction.current = action;
      action();
    },
    [job, settings],
  );

  const current = job.job;
  const liveActive = current?.kind === "live" && current.state === "live";
  const displayResult = useMemo(() => {
    if (!current) return null;
    if (current.kind === "live" && (current.state === "live" || (current.state !== "completed" && job.liveSegments.length))) {
      return job.liveSegments.length || job.result ? liveResultFrom(job.result, current, job.liveSegments) : null;
    }
    return current.state === "completed" ? job.result : null;
  }, [current, job.result, job.liveSegments]);

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <div className="hero-glow">
        <main className="mx-auto w-full max-w-5xl flex-1 space-y-5 px-4 pt-10 pb-4 sm:pt-14">
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mx-auto max-w-3xl text-center">
            <h1 className="text-3xl font-bold tracking-tight text-balance sm:text-5xl">
              YouTube to <span className="text-brand">Transcript</span> &amp; JSON Converter
            </h1>
            <p className="mt-3 text-base text-pretty text-muted-foreground sm:text-lg">
              Extract transcripts from YouTube videos and live streams. Copy or download your results instantly as TXT or JSON.
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5"><Captions className="size-3.5" /> Real YouTube captions</span>
              <span className="inline-flex items-center gap-1.5"><Radio className="size-3.5" /> Live streams where supported</span>
              <span className="inline-flex items-center gap-1.5"><FileText className="size-3.5" /> TXT export</span>
              <span className="inline-flex items-center gap-1.5"><Braces className="size-3.5" /> Structured JSON</span>
            </div>
          </motion.div>

          <UrlInputCard
            url={url}
            onUrlChange={setUrl}
            parsed={parsed}
            settings={settings}
            onSettingsChange={setSettings}
            info={info}
            capabilities={capabilities}
            busy={busy}
            onGenerate={generate}
            onUpload={upload}
          />

          <VideoPreviewCard info={info} loading={loading} error={error} />

          <ProcessingCard
            job={current}
            requestError={job.requestError}
            starting={job.starting}
            onCancel={job.cancel}
            onStop={job.stopLive}
            onRetry={() => lastAction.current?.()}
            onDismiss={job.reset}
          />

          {displayResult && current && (
            <ResultsSection
              key={current.job_id}
              result={displayResult}
              kind={current.kind}
              live={liveActive}
              defaultTimestamps={current.include_timestamps}
            />
          )}

          <div className="pt-6">
            <ConverterSection />
          </div>
        </main>
      </div>
      <SiteFooter capabilities={capabilities} />
    </div>
  );
}
