"use client";

import { ChevronRight } from "lucide-react";
import { createContext, memo, useContext, useEffect, useMemo, useState } from "react";

import { Highlight } from "@/components/highlight";
import { cn } from "@/lib/utils";

const PAGE = 200;

interface Ctx {
  re: RegExp | null;
  needle: string;
  signal: { open: boolean; n: number };
}
const JsonCtx = createContext<Ctx>({ re: null, needle: "", signal: { open: true, n: 0 } });

function Primitive({ value }: { value: unknown }) {
  const { re } = useContext(JsonCtx);
  if (value === null) return <span className="text-violet-600 dark:text-violet-400">null</span>;
  if (typeof value === "boolean") return <span className="text-violet-600 dark:text-violet-400">{String(value)}</span>;
  if (typeof value === "number") return <span className="text-amber-600 dark:text-amber-400">{String(value)}</span>;
  return (
    <span className="break-words text-emerald-700 dark:text-emerald-400">
      &quot;
      <Highlight text={JSON.stringify(value).slice(1, -1)} re={re} />
      &quot;
    </span>
  );
}

function Key({ name }: { name: string | number | null }) {
  const { re } = useContext(JsonCtx);
  if (name === null || typeof name === "number") return null;
  return (
    <>
      <span className="text-sky-700 dark:text-sky-400">
        &quot;
        <Highlight text={name} re={re} />
        &quot;
      </span>
      <span className="text-muted-foreground">: </span>
    </>
  );
}

function matchesNeedle(value: unknown, needle: string): boolean {
  if (!needle) return true;
  return JSON.stringify(value).toLowerCase().includes(needle);
}

const JsonNode = memo(function JsonNode({
  name,
  value,
  depth,
  comma,
}: {
  name: string | number | null;
  value: unknown;
  depth: number;
  comma: boolean;
}) {
  const { needle, signal } = useContext(JsonCtx);
  const isObj = value !== null && typeof value === "object";
  const [open, setOpen] = useState(depth < 3);
  const [limit, setLimit] = useState(PAGE);

  useEffect(() => {
    if (signal.n > 0) setOpen(signal.open || depth === 0);
  }, [signal, depth]);

  const entries = useMemo<Array<[string | number, unknown]>>(() => {
    if (!isObj) return [];
    if (Array.isArray(value)) {
      const all = value.map((v, i) => [i, v] as [number, unknown]);
      return needle && value.length > 20 ? all.filter(([, v]) => matchesNeedle(v, needle)) : all;
    }
    return Object.entries(value as Record<string, unknown>);
  }, [isObj, value, needle]);

  const pad = { paddingLeft: depth ? "1.1rem" : 0 };
  if (!isObj) {
    return (
      <div style={pad} className="transcript-line leading-6">
        <Key name={name} />
        <Primitive value={value} />
        {comma && <span className="text-muted-foreground">,</span>}
      </div>
    );
  }

  const isArr = Array.isArray(value);
  const total = isArr ? (value as unknown[]).length : entries.length;
  const [o, c] = isArr ? ["[", "]"] : ["{", "}"];
  const filtered = isArr && needle && entries.length !== total;

  return (
    <div style={pad}>
      <div className="leading-6">
        <button
          onClick={() => setOpen((v) => !v)}
          className="-ml-4 inline-flex w-4 items-center justify-center text-muted-foreground hover:text-foreground"
          aria-label={open ? "Collapse" : "Expand"}
          aria-expanded={open}
        >
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </button>
        <Key name={name} />
        <span className="text-muted-foreground">{o}</span>
        {!open && (
          <button onClick={() => setOpen(true)} className="mx-1 rounded bg-muted px-1.5 text-[11px] text-muted-foreground hover:text-foreground">
            {total} {isArr ? (total === 1 ? "item" : "items") : total === 1 ? "key" : "keys"}
          </button>
        )}
        {!open && <span className="text-muted-foreground">{c}{comma && ","}</span>}
        {open && filtered && (
          <span className="ml-2 text-[11px] text-muted-foreground">
            showing {entries.length} of {total} matching
          </span>
        )}
      </div>
      {open && (
        <>
          {entries.slice(0, limit).map(([k, v], i, arr) => (
            <JsonNode key={k} name={isArr ? null : k} value={v} depth={depth + 1} comma={i < arr.length - 1 || entries.length > limit} />
          ))}
          {entries.length > limit && (
            <div style={{ paddingLeft: "1.1rem" }} className="py-1">
              <button onClick={() => setLimit((l) => l + PAGE * 5)} className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">
                Show more ({entries.length - limit} remaining)
              </button>
              <button onClick={() => setLimit(entries.length)} className="ml-2 text-xs text-muted-foreground underline-offset-2 hover:underline">
                Show all
              </button>
            </div>
          )}
          <div className="leading-6 text-muted-foreground">
            {c}
            {comma && ","}
          </div>
        </>
      )}
    </div>
  );
});

export function JsonViewer({
  data,
  re,
  needle,
  signal,
  className,
}: {
  data: unknown;
  re: RegExp | null;
  needle: string;
  signal: { open: boolean; n: number };
  className?: string;
}) {
  const ctx = useMemo(() => ({ re, needle: needle.toLowerCase(), signal }), [re, needle, signal]);
  return (
    <JsonCtx.Provider value={ctx}>
      <div className={cn("overflow-auto rounded-xl border bg-muted/30 p-4 pl-6 font-mono text-[12.5px]", className)} role="tree">
        <JsonNode name={null} value={data} depth={0} comma={false} />
      </div>
    </JsonCtx.Provider>
  );
}
