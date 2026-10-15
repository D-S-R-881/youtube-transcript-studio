"use client";

import { motion } from "framer-motion";
import { CheckCircle2, ClipboardPaste, FileAudio, Link2, Loader2, Upload, Wand2, X, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { TranscriptSettingsPanel } from "@/components/transcript-settings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { readClipboardText } from "@/lib/clipboard";
import type { Capabilities, TranscriptSettings, VideoInfo } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { ParseResult } from "@/lib/youtube";

interface Props {
  url: string;
  onUrlChange: (url: string) => void;
  parsed: ParseResult | null;
  settings: TranscriptSettings;
  onSettingsChange: (s: TranscriptSettings) => void;
  info: VideoInfo | null;
  capabilities: Capabilities | null;
  busy: boolean;
  onGenerate: () => void;
  onUpload: (file: File) => void;
}

const MEDIA_ACCEPT = ".mp3,.wav,.m4a,.aac,.ogg,.oga,.opus,.flac,.wma,.mp4,.m4v,.mov,.mkv,.webm,.avi";

export function UrlInputCard(props: Props) {
  const { url, onUrlChange, parsed, settings, onSettingsChange, info, capabilities, busy, onGenerate, onUpload } = props;
  const [mode, setMode] = useState<"url" | "upload">("url");
  const [file, setFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const valid = parsed?.ok === true;
  const showError = parsed && !parsed.ok && url.trim().length > 0;
  const blocked = info && ["private", "deleted", "unavailable"].includes(info.availability);

  const paste = async () => {
    try {
      const text = (await readClipboardText()).trim();
      if (!text) return void toast.info("Your clipboard is empty.");
      onUrlChange(text);
    } catch (e) {
      toast.error((e as Error).message || "Clipboard access was denied.");
    }
  };

  const uploadEnabled = Boolean(capabilities?.file_upload);
  const maxMb = capabilities?.max_upload_mb ?? 0;

  const pickFile = (f: File | null) => {
    if (f && maxMb && f.size > maxMb * 1024 * 1024) {
      toast.error(`File is larger than the ${maxMb} MB limit.`);
      return;
    }
    setFile(f);
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="card-surface p-4 sm:p-6"
      aria-label="Transcript input"
    >
      <div className="mb-4 inline-flex rounded-lg bg-muted p-1 text-sm" role="tablist">
        {(
          [
            ["url", "YouTube URL", Link2],
            ["upload", "Upload media", FileAudio],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            role="tab"
            aria-selected={mode === key}
            onClick={() => setMode(key)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors",
              mode === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      {mode === "url" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid && !busy) onGenerate();
          }}
          className="space-y-3"
        >
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Link2 className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={url}
                onChange={(e) => onUrlChange(e.target.value)}
                placeholder="Paste a YouTube video or live stream URL here..."
                aria-label="YouTube URL"
                aria-invalid={showError ? true : undefined}
                autoComplete="off"
                spellCheck={false}
                inputMode="url"
                className={cn(
                  "h-12 rounded-xl pr-20 pl-11 text-base",
                  valid && "border-emerald-500/60 focus-visible:border-emerald-500 focus-visible:ring-emerald-500/20",
                )}
              />
              <div className="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1">
                {url && (
                  <span aria-live="polite" title={valid ? "Valid YouTube link" : "Invalid YouTube link"}>
                    {valid ? (
                      <CheckCircle2 className="size-5 text-emerald-500" />
                    ) : (
                      <XCircle className="size-5 text-destructive" />
                    )}
                  </span>
                )}
                {url && (
                  <Button type="button" variant="ghost" size="icon-sm" aria-label="Clear input" onClick={() => onUrlChange("")}>
                    <X />
                  </Button>
                )}
              </div>
            </div>
            <Button type="button" variant="outline" className="h-12 rounded-xl px-4" onClick={paste}>
              <ClipboardPaste /> Paste
            </Button>
            <Button
              type="submit"
              className="h-12 rounded-xl px-5 text-base shadow-md shadow-brand/25"
              disabled={!valid || busy || Boolean(blocked)}
            >
              {busy ? <Loader2 className="animate-spin" /> : <Wand2 />}
              Generate Transcript
            </Button>
          </div>
          <p className={cn("min-h-5 text-sm", showError ? "text-destructive" : "text-muted-foreground")} aria-live="polite">
            {showError
              ? (parsed as { ok: false; error: string }).error
              : valid
                ? `Video ID: ${parsed.value.videoId}${parsed.value.urlKind !== "video" ? ` · ${parsed.value.urlKind === "live" ? "Live URL" : "Shorts"}` : ""}`
                : "Supports youtube.com/watch, youtu.be, /live/, /shorts/ and m.youtube.com links."}
          </p>
        </form>
      ) : (
        <div className="space-y-3">
          {!uploadEnabled ? (
            <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
              <Upload className="mx-auto mb-2 size-6" />
              File transcription needs the speech-to-text service, which is not enabled on this server.
              {capabilities?.speech_to_text_reason && <p className="mt-1 text-xs">{capabilities.speech_to_text_reason}</p>}
            </div>
          ) : (
            <>
              <label
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  pickFile(e.dataTransfer.files?.[0] ?? null);
                }}
                className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-6 text-center transition-colors hover:border-brand/60 hover:bg-brand-soft/40"
              >
                <Upload className="size-6 text-muted-foreground" />
                <span className="text-sm font-medium">{file ? file.name : "Drop an audio/video file or click to choose"}</span>
                <span className="text-xs text-muted-foreground">
                  {file
                    ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
                    : `MP3, WAV, M4A, MP4, WEBM… up to ${maxMb} MB. Only upload media you have permission to process.`}
                </span>
                <input
                  ref={fileRef}
                  type="file"
                  accept={MEDIA_ACCEPT}
                  className="sr-only"
                  onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <div className="flex justify-end gap-2">
                {file && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setFile(null);
                      if (fileRef.current) fileRef.current.value = "";
                    }}
                  >
                    <X /> Clear
                  </Button>
                )}
                <Button className="h-10 px-5" disabled={!file || busy} onClick={() => file && onUpload(file)}>
                  {busy ? <Loader2 className="animate-spin" /> : <Wand2 />} Transcribe File
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      <Separator className="my-5" />
      <TranscriptSettingsPanel
        settings={settings}
        onChange={onSettingsChange}
        info={mode === "url" ? info : null}
        capabilities={capabilities}
        showLive={mode === "url" && (info?.video_type === "live" || (parsed?.ok === true && parsed.value.urlKind === "live"))}
        disabled={busy}
      />
    </motion.section>
  );
}
