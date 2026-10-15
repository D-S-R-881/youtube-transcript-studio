"use client";

import { motion } from "framer-motion";
import { ArrowRightLeft, Copy, Download, FileUp, Loader2, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { JsonViewer } from "@/components/json-viewer";
import { SearchBox } from "@/components/search-box";
import { useSearch } from "@/components/results-section";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { copyToClipboard } from "@/lib/clipboard";
import { downloadJson } from "@/lib/download";
import { exportFilename, resultToJson } from "@/lib/transcript-format";
import type { TranscriptResult } from "@/lib/types";

const MAX_MB = 20;
const OPEN_SIGNAL = { open: true, n: 0 };
const EXAMPLE = "[00:00:00] Hello everyone, welcome to today's video.\n\n[00:00:05] Today we are going to discuss artificial intelligence.\n\n[00:00:12] Let's get started.";

export function ConverterSection() {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TranscriptResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [query, setQuery] = useState("");
  const search = useSearch(query);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (f: File | null) => {
    if (!f) return;
    if (!/\.(txt|text|srt|vtt)$/i.test(f.name)) return void toast.error("Please choose a .txt transcript file.");
    if (f.size > MAX_MB * 1024 * 1024) return void toast.error(`File is larger than ${MAX_MB} MB.`);
    // Large files are sent as-is instead of being loaded into the textarea, which keeps the page responsive.
    setFile(f);
    setText("");
    setResult(null);
    setError(null);
  };

  const clearFile = () => {
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const convert = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.convertTxt(file ? { file } : { text });
      setResult(res);
      toast.success(`Converted ${res.total_segments.toLocaleString()} segments to JSON`);
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e : new ApiError("unknown", "Conversion failed.", 0));
    } finally {
      setBusy(false);
    }
  };

  const matches = useMemo(
    () => (result && search.re ? JSON.stringify(result).match(search.re)?.length ?? 0 : 0),
    [result, search.re],
  );
  const name = result ? exportFilename({ ...result, title: result.title ?? "converted" }, "json") : "";

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      className="card-surface p-4 sm:p-6"
      id="converter"
      aria-label="TXT to JSON converter"
    >
      <div className="mb-4 flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
          <ArrowRightLeft className="size-4" />
        </span>
        <div>
          <h2 className="text-lg font-semibold tracking-tight">TXT to JSON Converter</h2>
          <p className="text-sm text-muted-foreground">
            Upload or paste a transcript. Timestamps like <code className="font-mono text-xs">[00:01:05]</code>,{" "}
            <code className="font-mono text-xs">0:05</code> or SRT/VTT cues are preserved; untimed text is split by
            paragraph without inventing timestamps.
          </p>
        </div>
      </div>

      <div className="grid gap-3">
        {file ? (
          <div className="flex items-center gap-3 rounded-xl border bg-muted/30 p-3 text-sm">
            <FileUp className="size-5 text-brand" />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{file.name}</p>
              <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB</p>
            </div>
            <Button variant="ghost" size="icon-sm" aria-label="Remove file" onClick={clearFile}>
              <X />
            </Button>
          </div>
        ) : (
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              pick(e.dataTransfer.files?.[0] ?? null);
            }}
          >
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={`Paste transcript text here, or drop a .txt file…\n\n${EXAMPLE}`}
              className="min-h-40 font-mono text-[13px]"
              aria-label="Transcript text"
            />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => inputRef.current?.click()}>
            <FileUp /> Upload .txt
          </Button>
          <input ref={inputRef} type="file" accept=".txt,.text,.srt,.vtt,text/plain" className="sr-only" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          {!file && !text && (
            <Button variant="ghost" size="sm" onClick={() => setText(EXAMPLE)}>
              Use example
            </Button>
          )}
          <div className="flex-1" />
          <Button onClick={convert} disabled={busy || (!file && !text.trim())}>
            {busy ? <Loader2 className="animate-spin" /> : <ArrowRightLeft />} Convert to JSON
          </Button>
        </div>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error.message}
            {error.hint && <span className="block text-muted-foreground">{error.hint}</span>}
          </p>
        )}
      </div>

      {result && (
        <div className="mt-5 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{result.total_segments.toLocaleString()} segments</Badge>
            <Badge variant="outline">{result.has_timestamps ? "Timestamps preserved" : "No timestamps"}</Badge>
            <SearchBox value={query} onChange={setQuery} matches={matches} placeholder="Search JSON" />
            <Button variant="outline" onClick={() => copyToClipboard(resultToJson(result)).then(() => toast.success("JSON copied to clipboard"), (e) => toast.error(e.message))}>
              <Copy /> Copy JSON
            </Button>
            <Button
              onClick={() => {
                downloadJson(resultToJson(result), name);
                toast.success(`Downloaded ${name}`);
              }}
            >
              <Download /> Download JSON
            </Button>
          </div>
          <JsonViewer data={result} re={search.re} needle={search.needle} signal={OPEN_SIGNAL} className="max-h-[28rem]" />
        </div>
      )}
    </motion.section>
  );
}
