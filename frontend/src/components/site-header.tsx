"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

export function Logo({ className = "size-9" }: { className?: string }) {
  return (
    <span className={`grid place-items-center rounded-xl bg-brand text-white shadow-sm shadow-brand/30 ${className}`}>
      <svg viewBox="0 0 24 24" className="size-[55%]" fill="currentColor" aria-hidden>
        <path d="M8 5.5v13l10.5-6.5L8 5.5z" />
      </svg>
    </span>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = mounted && resolvedTheme === "dark";
  return (
    <Button
      variant="outline"
      size="icon"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="rounded-full"
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/75 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 max-w-5xl items-center gap-3 px-4">
        <Logo />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold leading-tight tracking-tight">YouTube Transcript Studio</p>
          <p className="hidden truncate text-xs text-muted-foreground sm:block">
            Turn YouTube Videos &amp; Live Streams into Text and JSON in Seconds
          </p>
        </div>
        <ThemeToggle />
      </div>
    </header>
  );
}
