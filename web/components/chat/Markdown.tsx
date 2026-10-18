// Light markdown for the assistant's words, rendered at display (the stored and streamed text stays as written): bold,
// italic, inline code, bullet and numbered lists, headings as bold lines, links to http(s) only. Builds React elements,
// never HTML, so anything else in the text shows as the plain characters it is.
import type { ReactNode } from "react";

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*|__[^_\n]+?__)|(\*[^*\s][^*\n]*?\*(?![\w*])|_[^_\s][^_\n]*?_(?!\w))|(\[[^\]\n]+\]\([^)\s]+\))/;

function inline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text, n = 0;
  for (let m = INLINE.exec(rest); m; m = INLINE.exec(rest)) {
    // no lookbehind (older Safari can't parse it): an italic mark right after a letter or digit (2*3*4, snake_case)
    // is just a character
    if (m[3] && m.index && /[\w*]/.test(rest[m.index - 1])) {
      out.push(rest.slice(0, m.index + 1)); rest = rest.slice(m.index + 1); continue;
    }
    if (m.index) out.push(rest.slice(0, m.index));
    const t = m[0], k = `${key}.${n++}`;
    if (m[1]) out.push(<code key={k}>{t.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k}>{inline(t.slice(2, -2), k)}</strong>);
    else if (m[3]) out.push(<em key={k}>{inline(t.slice(1, -1), k)}</em>);
    else {
      const [, label, url] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t)!;
      out.push(/^https?:\/\//i.test(url)
        ? <a key={k} href={url} target="_blank" rel="noopener noreferrer">{inline(label, k)}</a>
        : <span key={k}>{inline(label, k)}</span>);
    }
    rest = rest.slice(m.index + t.length);
  }
  if (rest) out.push(rest);
  return out;
}

type Item = { text: string; subs: string[] }; // subs: the indented items under it
type Block = { kind: "p"; lines: string[] } | { kind: "h"; text: string } | { kind: "ul" | "ol"; items: Item[]; start: number };

function blocks(src: string): Block[] {
  const out: Block[] = [];
  const last = () => out[out.length - 1];
  for (const raw of src.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^(\s*)[-*•]\s+(.*)$/.exec(line);
    const num = /^(\s*)(\d{1,3})[.)]\s+(.*)$/.exec(line);
    const head = /^\s*#{1,6}\s+(.*)$/.exec(line);
    if (!line.trim() || /^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push({ kind: "p", lines: [] }); continue; }
    if (head) { out.push({ kind: "h", text: head[1].replace(/\s*#+$/, "") }); continue; }
    if (bullet || num) {
      const kind = bullet ? "ul" : "ol";
      const indent = (bullet ?? num)![1].length;
      const text = bullet ? bullet[2] : num![3];
      const l = last();
      // an indented item stays inside the list above it, whichever kind that is
      if ((l?.kind === "ul" || l?.kind === "ol") && indent >= 2) l.items[l.items.length - 1].subs.push(text);
      else if (l && l.kind === kind) l.items.push({ text, subs: [] });
      else out.push({ kind, items: [{ text, subs: [] }], start: num ? Number(num[2]) : 1 });
      continue;
    }
    const l = last();
    if (l?.kind === "p") l.lines.push(line.trim());
    else if ((l?.kind === "ul" || l?.kind === "ol") && /^\s{2,}/.test(raw)) {
      const it = l.items[l.items.length - 1];
      if (it.subs.length) it.subs[it.subs.length - 1] += " " + line.trim(); else it.text += " " + line.trim();
    }
    else out.push({ kind: "p", lines: [line.trim()] });
  }
  return out.filter((b) => b.kind !== "p" || b.lines.length);
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {blocks(text).map((b, i) => {
        if (b.kind === "h") return <p key={i}><strong>{inline(b.text, `${i}`)}</strong></p>;
        if (b.kind === "p") return <p key={i}>{b.lines.flatMap((l, j) => j ? [<br key={`b${j}`} />, ...inline(l, `${i}.${j}`)] : inline(l, `${i}.${j}`))}</p>;
        const items = b.items.map((it, j) => (
          <li key={j}>{inline(it.text, `${i}.${j}`)}
            {it.subs.length > 0 && <ul>{it.subs.map((t, k) => <li key={k}>{inline(t, `${i}.${j}.${k}`)}</li>)}</ul>}</li>));
        return b.kind === "ul" ? <ul key={i}>{items}</ul> : <ol key={i} start={b.start}>{items}</ol>;
      })}
    </div>
  );
}
