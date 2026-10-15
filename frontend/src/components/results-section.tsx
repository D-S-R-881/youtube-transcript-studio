"use client";

import { motion } from "framer-motion";
import { Braces, ChevronsDownUp, ChevronsUpDown, Copy, Download, FileText, Languages, Radio } from "lucide-react";
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Highlight } from "@/components/highlight";
import { JsonViewer } from "@/components/json-viewer";
import { SearchBox } from "@/components/search-box";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { copyToClipboard } from "@/lib/clipboard";
import { downloadJson, downloadTxt } from "@/lib/download";
import {
  buildParagraphs,
  buildTxt,
  countChars,
  countWords,
  escapeRegExp,
  exportFilename,
  formatTimestamp,
  resultToJson,
} from "@/lib/transcript-format";
import type { Segment, TranscriptResult } from "@/lib/types";

const SOURCE_LABEL: Record<TranscriptResult["transcript_source"], string> = {
  youtube_captions: "YouTube captions",
  speech_to_text: "Speech-to-text",
  youtube_live_captions: "Live captions",
  live_speech_to_text: "Live speech-to-text",
  uploaded_file_stt: "Uploaded file (speech-to-text)",
  txt_import: "TXT import",
};

export function useSearch(query: string) {
  const deferred = useDeferredValue(query.trim());
  const re = useMemo(() => (deferred ? new RegExp(escapeRegExp(deferred), "giu") : null), [deferred]);
  return { needle: deferred, re };
}

function useMatchNavigator(containerRef: React.RefObject<HTMLElement | null>, deps: unknown[]) {
  const [index, setIndex] = useState(-1);
  useEffect(() => setIndex(-1), deps); // eslint-disable-line react-hooks/exhaustive-deps
  const go = useCallback(
    (dir: 1 | -1) => {
      const marks = containerRef.current?.querySelectorAll<HTMLElement>("mark.search-hit");
      if (!marks?.length) return;
      const next = (index + dir + marks.length) % marks.length;
      marks.forEach((m) => m.removeAttribute("data-current"));
      marks[next].setAttribute("data-current", "true");
      marks[next].scrollIntoView({ block: "center", behavior: "smooth" });
      setIndex(next);
    },
    [containerRef, index],
  );
  return { next: () => go(1), prev: () => go(-1) };
}

function countMatches(text: string, re: RegExp | null): number {
  if (!re) return 0;
  return text.match(re)?.length ?? 0;
}

function TxtViewer({ segments, showTimestamps, re, live }: { segments: Segment[]; showTimestamps: boolean; re: RegExp | null; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const paragraphs = useMemo(() => (showTimestamps ? null : buildParagraphs(segments)), [segments, showTimestamps]);

  useEffect(() => {
    const el = ref.current;
    if (live && el && stick.current) el.scrollTop = el.scrollHeight;
  }, [segments.length, live]);

  return (
    <div
      ref={ref}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      }}
      className="max-h-[32rem] min-h-48 overflow-auto rounded-xl border bg-muted/30 p-4 text-[15px] leading-7"
      data-testid="txt-viewer"
    >
      {showTimestamps
        ? segments.map((s) => (
            <p key={s.id} className="transcript-line mb-3 last:mb-0">
              {s.start != null && <span className="mr-2 font-mono text-xs text-brand select-all">[{formatTimestamp(s.start)}]</span>}
              <Highlight text={s.text} re={re} />
            </p>
          ))
        : paragraphs!.map((p, i) => (
            <p key={i} className="transcript-line mb-4 last:mb-0">
              <Highlight text={p} re={re} />
            </p>
          ))}
    </div>
  );
}

interface Props {
  result: TranscriptResult;
  kind?: string;
  live: boolean;
  defaultTimestamps: boolean;
}

export function ResultsSection({ result, kind, live, defaultTimestamps }: Props) {
  const [tab, setTab] = useState<"txt" | "json">("txt");
  const [showTimestamps, setShowTimestamps] = useState(defaultTimestamps && result.has_timestamps);
  const [txtQuery, setTxtQuery] = useState("");
  const [jsonQuery, setJsonQuery] = useState("");
  const [signal, setSignal] = useState({ open: true, n: 0 });
  const txtSearch = useSearch(txtQuery);
  const jsonSearch = useSearch(jsonQuery);
  const txtWrap = useRef<HTMLDivElement>(null);
  const jsonWrap = useRef<HTMLDivElement>(null);
  const txtNav = useMatchNavigator(txtWrap, [txtSearch.needle, showTimestamps]);
  const jsonNav = useMatchNavigator(jsonWrap, [jsonSearch.needle]);

  const hasTimes = result.has_timestamps && result.transcript.some((s) => s.start != null);
  useEffect(() => {
    if (!hasTimes) setShowTimestamps(false);
  }, [hasTimes]);

  const txt = useMemo(() => buildTxt(result.transcript, showTimestamps), [result.transcript, showTimestamps]);
  const deferredFull = useDeferredValue(result.full_text);
  const words = useMemo(() => countWords(deferredFull), [deferredFull]);
  const chars = useMemo(() => countChars(txt), [txt]);
  const txtMatches = useMemo(() => countMatches(result.full_text, txtSearch.re), [result.full_text, txtSearch.re]);
  const jsonMatches = useMemo(
    () => (tab === "json" && jsonSearch.re ? countMatches(JSON.stringify(result), jsonSearch.re) : 0),
    [tab, result, jsonSearch.re],
  );

  const run = async (fn: () => void | Promise<void>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
    } catch (e) {
      toast.error((e as Error).message || "Action failed.");
    }
  };
  const copyTxt = () => run(() => copyToClipboard(txt), "Transcript text copied to clipboard");
  const dlTxt = () => {
    const name = exportFilename(result, "txt", kind);
    run(() => downloadTxt(txt, name), `Downloaded ${name}`);
  };
  const copyJson = () => run(() => copyToClipboard(resultToJson(result)), "JSON copied to clipboard");
  const dlJson = () => {
    const name = exportFilename(result, "json", kind);
    run(() => downloadJson(resultToJson(result), name), `Downloaded ${name}`);
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="card-surface p-4 sm:p-6"
      aria-label="Transcript results"
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold tracking-tight">{live ? "Live transcript" : "Your transcript"}</h2>
        {live && (
          <Badge className="bg-brand text-white">
            <Radio /> Updating live
          </Badge>
        )}
        <Badge variant="secondary">{SOURCE_LABEL[result.transcript_source]}</Badge>
        {result.caption_type && <Badge variant="outline">{result.caption_type === "manual" ? "Manual captions" : "Auto-generated"}</Badge>}
        <Badge variant="outline">
          <Languages /> {result.language_name ?? result.language ?? "Language unknown"}
          {result.translated_from && ` (from ${result.translated_from})`}
        </Badge>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as "txt" | "json")}>
        <TabsList className="h-10 w-full sm:w-auto">
          <TabsTrigger value="txt" className="px-4">
            <FileText /> TXT Transcript
          </TabsTrigger>
          <TabsTrigger value="json" className="px-4">
            <Braces /> JSON Transcript
          </TabsTrigger>
        </TabsList>

        <TabsContent value="txt" className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchBox value={txtQuery} onChange={setTxtQuery} matches={txtMatches} onNext={txtNav.next} onPrev={txtNav.prev} />
            <div className="flex items-center gap-2 pr-1">
              <Switch id="show-ts" checked={showTimestamps} onCheckedChange={(c) => setShowTimestamps(Boolean(c))} disabled={!hasTimes} />
              <Label htmlFor="show-ts" className="text-sm">
                Timestamps
              </Label>
            </div>
            <Button variant="outline" onClick={copyTxt}>
              <Copy /> Copy Text
            </Button>
            <Button onClick={dlTxt}>
              <Download /> Download TXT
            </Button>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground tabular-nums">
            <span>{words.toLocaleString()} words</span>
            <span>{chars.toLocaleString()} characters</span>
            <span>{result.total_segments.toLocaleString()} segments</span>
            <span>Language: {result.language ?? "unknown"}</span>
            {result.timestamp_reference === "session_start" && <span>Timestamps relative to when this session started</span>}
          </div>
          <div ref={txtWrap}>
            <TxtViewer segments={result.transcript} showTimestamps={showTimestamps} re={txtSearch.re} live={live} />
          </div>
        </TabsContent>

        <TabsContent value="json" className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchBox value={jsonQuery} onChange={setJsonQuery} matches={jsonMatches} onNext={jsonNav.next} onPrev={jsonNav.prev} placeholder="Search JSON" />
            <Button variant="ghost" size="sm" onClick={() => setSignal((s) => ({ open: true, n: s.n + 1 }))}>
              <ChevronsUpDown /> Expand
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSignal((s) => ({ open: false, n: s.n + 1 }))}>
              <ChevronsDownUp /> Collapse
            </Button>
            <Button variant="outline" onClick={copyJson}>
              <Copy /> Copy JSON
            </Button>
            <Button onClick={dlJson}>
              <Download /> Download JSON
            </Button>
          </div>
          <div ref={jsonWrap}>
            {tab === "json" && (
              <JsonViewer data={result} re={jsonSearch.re} needle={jsonSearch.needle} signal={signal} className="max-h-[32rem] min-h-48" />
            )}
          </div>
        </TabsContent>
      </Tabs>
    </motion.section>
  );
}
