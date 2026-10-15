"use client";

import { Clock, Languages, Radio, Sparkles } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { Capabilities, TranscriptSettings, VideoInfo } from "@/lib/types";

const WHISPER_LANGUAGES: Array<[string, string]> = [
  ["en", "English"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["it", "Italian"], ["pt", "Portuguese"],
  ["nl", "Dutch"], ["ru", "Russian"], ["uk", "Ukrainian"], ["pl", "Polish"], ["tr", "Turkish"], ["ar", "Arabic"],
  ["hi", "Hindi"], ["bn", "Bengali"], ["ta", "Tamil"], ["te", "Telugu"], ["mr", "Marathi"], ["ur", "Urdu"],
  ["ja", "Japanese"], ["ko", "Korean"], ["zh", "Chinese"], ["id", "Indonesian"], ["vi", "Vietnamese"], ["th", "Thai"],
];

interface Option {
  value: string;
  label: string;
}

export function languageGroups(info: VideoInfo | null, source: TranscriptSettings["source"]) {
  const groups: Array<{ label: string; options: Option[] }> = [];
  const tracks = info?.caption_tracks ?? [];
  if (source !== "speech_to_text" && tracks.length) {
    groups.push({
      label: "Available captions",
      options: tracks.map((t) => ({
        value: t.language_code,
        label: `${t.language}${t.is_generated ? " (auto-generated)" : ""}`,
      })),
    });
    const have = new Set(tracks.map((t) => t.language_code));
    const translations = (info?.translation_languages ?? []).filter((t) => !have.has(t.language_code));
    if (translations.length) {
      groups.push({
        label: "Translate captions to",
        options: translations.map((t) => ({ value: t.language_code, label: `${t.language} (translated)` })),
      });
    }
  } else if (source === "speech_to_text" || !tracks.length) {
    groups.push({
      label: "Spoken language",
      options: WHISPER_LANGUAGES.map(([value, label]) => ({ value, label })),
    });
  }
  return groups;
}

interface Props {
  settings: TranscriptSettings;
  onChange: (s: TranscriptSettings) => void;
  info: VideoInfo | null;
  capabilities: Capabilities | null;
  showLive: boolean;
  disabled?: boolean;
}

export function TranscriptSettingsPanel({ settings, onChange, info, capabilities, showLive, disabled }: Props) {
  const set = <K extends keyof TranscriptSettings>(k: K, v: TranscriptSettings[K]) => onChange({ ...settings, [k]: v });
  const groups = languageGroups(info, settings.source);
  const languageItems = [{ value: "auto", label: "Auto-detect" }, ...groups.flatMap((g) => g.options)];
  const sttAllowed = Boolean(capabilities?.youtube_audio_ingestion);

  const sourceItems = [
    { value: "auto", label: "Auto (captions first)" },
    { value: "captions", label: "Existing captions only" },
    { value: "speech_to_text", label: sttAllowed ? "Speech-to-text" : "Speech-to-text (not enabled)" },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div className="grid gap-1.5">
        <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Languages className="size-3.5" /> Transcript language
        </Label>
        <Select
          items={languageItems}
          value={languageItems.some((i) => i.value === settings.language) ? settings.language : "auto"}
          onValueChange={(v) => set("language", (v as string) ?? "auto")}
          disabled={disabled}
        >
          <SelectTrigger className="w-full" aria-label="Transcript language">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="max-h-80">
            <SelectItem value="auto">Auto-detect</SelectItem>
            {groups.map((g) => (
              <SelectGroup key={g.label}>
                <SelectLabel>{g.label}</SelectLabel>
                {g.options.map((o) => (
                  <SelectItem key={`${g.label}-${o.value}`} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-1.5">
        <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Sparkles className="size-3.5" /> Transcript source
        </Label>
        <Select
          items={sourceItems}
          value={settings.source}
          onValueChange={(v) => set("source", (v as TranscriptSettings["source"]) ?? "auto")}
          disabled={disabled}
        >
          <SelectTrigger className="w-full" aria-label="Transcript source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {sourceItems.map((o) => (
              <SelectItem key={o.value} value={o.value} disabled={o.value === "speech_to_text" && !sttAllowed}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="ts-switch" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock className="size-3.5" /> Include timestamps
        </Label>
        <div className="flex h-8 items-center gap-2">
          <Switch
            id="ts-switch"
            checked={settings.includeTimestamps}
            onCheckedChange={(c) => set("includeTimestamps", Boolean(c))}
            disabled={disabled}
          />
          <span className="text-sm">{settings.includeTimestamps ? "On" : "Off"}</span>
        </div>
      </div>

      {showLive && (
        <div className="grid gap-1.5">
          <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Radio className="size-3.5" /> Live transcription mode
          </Label>
          <div className="flex gap-2">
            <Select
              items={[
                { value: "continuous", label: "Until I stop" },
                { value: "timed", label: "Fixed duration" },
              ]}
              value={settings.liveMode}
              onValueChange={(v) => set("liveMode", (v as TranscriptSettings["liveMode"]) ?? "continuous")}
              disabled={disabled}
            >
              <SelectTrigger className="w-full" aria-label="Live transcription mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="continuous">Until I stop</SelectItem>
                <SelectItem value="timed">Fixed duration</SelectItem>
              </SelectContent>
            </Select>
            {settings.liveMode === "timed" && (
              <div className="relative w-24 shrink-0">
                <Input
                  type="number"
                  min={1}
                  max={240}
                  value={settings.liveMaxMinutes}
                  onChange={(e) => set("liveMaxMinutes", Math.min(240, Math.max(1, Number(e.target.value) || 1)))}
                  aria-label="Live duration in minutes"
                  className="pr-9"
                  disabled={disabled}
                />
                <span className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 text-xs text-muted-foreground">
                  min
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
