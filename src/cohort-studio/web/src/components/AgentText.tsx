import { Fragment, ReactNode } from "react";

function inline(text: string, depth = 0): ReactNode[] {
  if (depth > 4) return [text];
  const pattern = /\[([^\]\n]{1,500})\]\((https:\/\/[^\s)]+)\)|\*\*([^*\n]+)\*\*|`([^`\n]+)`|\*([^*\n]+)\*/g;
  const result: ReactNode[] = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    result.push(<Fragment key={`text-${index}`}>{text.slice(offset, index)}</Fragment>);
    if (match[1]) {
      try {
        const url = new URL(match[2]);
        if (url.username || url.password) throw new Error("Invalid citation URL");
        result.push(<a key={index} href={url.href} target="_blank" rel="noopener noreferrer">{inline(match[1], depth + 1)}</a>);
      } catch { result.push(<Fragment key={index}>{match[0]}</Fragment>); }
    } else if (match[3]) result.push(<strong key={index}>{inline(match[3], depth + 1)}</strong>);
    else if (match[4]) result.push(<code key={index}>{match[4]}</code>);
    else result.push(<em key={index}>{match[5]}</em>);
    offset = index + match[0].length;
  }
  result.push(<Fragment key="tail">{text.slice(offset)}</Fragment>);
  return result;
}

export function AgentText({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    if (!lines[i].trim()) { i++; continue; }
    const start = i;
    if (/^\s*```/.test(lines[i])) {
      i++;
      const code: string[] = [];
      while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
      if (i < lines.length) i++;
      blocks.push(<pre key={start}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const item = lines[i].match(/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/);
    if (item) {
      const ordered = Boolean(item[2]);
      const items: ReactNode[] = [];
      while (i < lines.length) {
        const next = lines[i].match(/^\s*(?:([-*+])|(\d+)\.)\s+(.+)$/);
        if (!next || Boolean(next[2]) !== ordered) break;
        items.push(<li key={i}>{inline(next[3])}</li>); i++;
      }
      blocks.push(ordered ? <ol key={start}>{items}</ol> : <ul key={start}>{items}</ul>);
      continue;
    }
    const heading = lines[i].match(/^\s*#{1,6}\s+(.+)$/);
    if (heading) { blocks.push(<p className="agent-text-heading" key={i++}><strong>{inline(heading[1])}</strong></p>); continue; }
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^\s*(?:```|#{1,6}\s|[-*+]\s|\d+\.\s)/.test(lines[i])) paragraph.push(lines[i++]);
    blocks.push(<p key={start}>{inline(paragraph.join("\n"))}</p>);
  }
  return <div className="agent-text">{blocks}</div>;
}
