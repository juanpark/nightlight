/** "just now", "2 min ago", "3 h ago", or a short date for anything older than two days. */
export function timeAgo(d: Date | null | undefined, now = Date.now()): string {
  if (!d) return "never";
  const s = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
