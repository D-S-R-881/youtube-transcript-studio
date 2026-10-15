export function downloadText(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after the click has been processed so the download can start.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const downloadTxt = (content: string, filename: string) => downloadText(content, filename, "text/plain");
export const downloadJson = (content: string, filename: string) =>
  downloadText(content, filename, "application/json");
