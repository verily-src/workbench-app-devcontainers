import { Fragment } from "react";

export function AgentText({ text }: { text: string }) {
  const pattern = /\[([^\]\n]{1,500})\]\((https:\/\/[^\s)]+)\)/g;
  const parts = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    parts.push(<Fragment key={`text-${index}`}>{text.slice(offset, index)}</Fragment>);
    try {
      const url = new URL(match[2]);
      if (url.username || url.password) throw new Error("Invalid citation URL");
      parts.push(<a key={`link-${index}`} href={url.href} target="_blank" rel="noopener noreferrer">{match[1]}</a>);
    } catch {
      parts.push(<Fragment key={`invalid-${index}`}>{match[0]}</Fragment>);
    }
    offset = index + match[0].length;
  }
  parts.push(<Fragment key="tail">{text.slice(offset)}</Fragment>);
  return <>{parts}</>;
}
