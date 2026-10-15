import type { Capabilities } from "@/lib/types";

export function SiteFooter({ capabilities }: { capabilities: Capabilities | null }) {
  return (
    <footer className="mt-16 border-t">
      <div className="mx-auto grid max-w-5xl gap-4 px-4 py-8 text-xs leading-relaxed text-muted-foreground sm:grid-cols-3">
        <div>
          <p className="mb-1 font-medium text-foreground">Transcript availability</p>
          Transcripts come from existing YouTube captions (manual captions are preferred over auto-generated ones).
          Videos whose uploader disabled captions, private, deleted, members-only or region-locked videos can&apos;t be
          transcribed from captions.
        </div>
        <div>
          <p className="mb-1 font-medium text-foreground">Speech-to-text &amp; live streams</p>
          {capabilities?.speech_to_text
            ? `Speech-to-text (Whisper ${capabilities.whisper_model ?? ""}) is available for files you upload${
                capabilities.youtube_audio_ingestion ? " and for permitted YouTube audio" : ""
              }.`
            : "Speech-to-text is not enabled on this server."}{" "}
          Live transcription depends on live captions or permitted audio access and is not available for every broadcast.
        </div>
        <div>
          <p className="mb-1 font-medium text-foreground">Privacy</p>
          Transcripts are kept in server memory only and deleted automatically
          {capabilities ? ` after ${Math.round(capabilities.job_ttl_seconds / 60)} minutes` : ""}. Not affiliated with
          YouTube or Google.
        </div>
      </div>
    </footer>
  );
}
