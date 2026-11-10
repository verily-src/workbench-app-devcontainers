import type { ReactNode } from "react";
import { useMediaQuery } from "../libs/hooks";

// Below this the two step panels no longer fit side by side, so they stack.
const NARROW_LAYOUT_QUERY = "(max-width: 720px)";

/** Lays out VariantsStep and PhenotypeStep side by side, stacking them on narrow screens. */
export default function SearchSteps({ children }: { children: ReactNode }) {
  const isNarrow = useMediaQuery(NARROW_LAYOUT_QUERY);
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: isNarrow ? "1fr" : "1fr 1fr",
        gap: 20,
        alignItems: "stretch",
      }}
    >
      {children}
    </div>
  );
}
