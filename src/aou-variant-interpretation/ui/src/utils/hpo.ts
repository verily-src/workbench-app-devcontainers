import type { HpoTerm } from "../api/conditions";

// One voice for a condition's HPO term, wherever it shows: the dropdown option, the picked chip
// and the results strip. The id is the label, prefixed "≈" when the term is only a broader phrase
// the concept's name contains; the tooltip carries the term's name and the caveat; the spoken form
// is for accessible names, which don't get the glyph.

export interface HpoWords {
  /** The id, or "≈ " and the id for a nearest match. */
  label: string;
  /** The full story, for a title attribute. */
  tooltip: string;
  /** The same for an accessible name, where the glyph would be read as a symbol. */
  spoken: string;
}

/** How a concept's HPO term is worded; `link` adds that following it opens the HPO browser. */
export function describeHpo(hpo: HpoTerm, { link = false }: { link?: boolean } = {}): HpoWords {
  const exact = hpo.match === "exact";
  const words: HpoWords = exact
    ? {
        label: hpo.id,
        tooltip: `HPO ${hpo.id} ${hpo.name}. Matched on the condition's name.`,
        spoken: `HPO term ${hpo.id}, ${hpo.name}`,
      }
    : {
        label: `≈ ${hpo.id}`,
        tooltip: `Nearest HPO term: ${hpo.id} ${hpo.name}. Broader than the condition; no exact term matched its name.`,
        spoken: `nearest HPO term ${hpo.id}, ${hpo.name}`,
      };
  return link ? { ...words, tooltip: `${words.tooltip} Opens the HPO browser.`, spoken: `${words.spoken}, opens the HPO browser` } : words;
}
