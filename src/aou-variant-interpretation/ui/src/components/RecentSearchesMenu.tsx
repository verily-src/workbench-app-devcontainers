import type { CSSProperties } from "react";
import colors from "../libs/colors";
import * as Style from "../libs/style";
import { describeSearchedAt, type RecentSearch } from "../utils/recentSearches";
import { describeAlternatives } from "../utils/phenotypes";
import LinkMenu from "./LinkMenu";

/** Variant IDs shown before the rest are summarised as "+N more". */
const PREVIEW_VARIANTS = 3;

const styles = {
  none: {
    color: colors.textSecondary,
    fontWeight: 500,
  },
  variants: {
    ...Style.elements.mono,
    display: "block",
    overflow: "hidden",
    fontSize: 11,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
} as const satisfies Record<string, CSSProperties>;

function previewVariants(variants: string[]): string {
  const shown = variants.slice(0, PREVIEW_VARIANTS).join(", ");
  const rest = variants.length - PREVIEW_VARIANTS;
  return rest > 0 ? `${shown} +${rest} more` : shown;
}

/** The search's conditions as the search treats them, "A or B"; empty when it had none. */
export const describeConditions = (search: RecentSearch) =>
  describeAlternatives(search.conditions.map((condition) => condition.name));

interface RecentSearchesMenuProps {
  searches: RecentSearch[];
  onPick: (search: RecentSearch) => void;
}

export default function RecentSearchesMenu({ searches, onPick }: RecentSearchesMenuProps) {
  return (
    <LinkMenu
      label="Recent searches"
      menuLabel="Recent searches"
      width={380}
      items={searches.map((search) => ({
        key: `search-${search.searchedAt}`,
        title: search.conditions.length > 0 ? describeConditions(search) : <span style={styles.none}>No phenotype</span>,
        meta: describeSearchedAt(search.searchedAt),
        description: (
          <span style={styles.variants} title={search.variants.join("\n")}>
            {previewVariants(search.variants)}
          </span>
        ),
        onPick: () => onPick(search),
      }))}
    />
  );
}
