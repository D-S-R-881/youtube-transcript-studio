"use client";

import { ChevronDown, ChevronUp, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  value: string;
  onChange: (v: string) => void;
  matches: number;
  onNext?: () => void;
  onPrev?: () => void;
  placeholder?: string;
}

export function SearchBox({ value, onChange, matches, onNext, onPrev, placeholder = "Search transcript" }: Props) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      <div className="relative min-w-0 flex-1 sm:max-w-xs">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.shiftKey ? onPrev : onNext)?.();
            if (e.key === "Escape") onChange("");
          }}
          placeholder={placeholder}
          aria-label={placeholder}
          className="h-8 pr-16 pl-8"
        />
        {value && (
          <span className="absolute top-1/2 right-7 -translate-y-1/2 text-[11px] text-muted-foreground tabular-nums">{matches}</span>
        )}
        {value && (
          <button
            aria-label="Clear search"
            onClick={() => onChange("")}
            className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>
      {value && onNext && (
        <>
          <Button variant="ghost" size="icon-sm" aria-label="Previous match" onClick={onPrev} disabled={!matches}>
            <ChevronUp />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label="Next match" onClick={onNext} disabled={!matches}>
            <ChevronDown />
          </Button>
        </>
      )}
    </div>
  );
}
