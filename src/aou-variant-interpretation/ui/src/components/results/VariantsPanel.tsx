import { Fragment, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { flexRender, type SortingState } from "@tanstack/react-table";
import {
  getCoreRowModel,
  getSortedRowModel,
  legacyCreateColumnHelper as createColumnHelper,
  useLegacyTable as useReactTable,
} from "@tanstack/react-table/legacy";
import colors, { alpha, sourceTints } from "../../libs/colors";
import { useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import type { ClinVarSignificance, CohortVariantRow, FilteredVariantRow } from "../../types/results";
import { mergeVariantRows, type MergedVariantRow } from "../../utils/comparison";
import { clinvarSearchUrl, gnomadVariantUrl } from "../../utils/externalLinks";
import { exactAf, formatAcAn, formatAf, formatInt } from "../../utils/format";
import { describeAlternatives } from "../../utils/phenotypes";
import { AOU_SUBPOP_CODES, GNOMAD_SUBPOP_CODES } from "../../utils/subpopulations";
import Clickable from "../common/Clickable";
import AllOfUs from "../common/AllOfUs";
import InfoLabel from "../common/InfoLabel";
import { ChevronRightIcon, CompareIcon, EyeOffIcon, SortIcon, UserIcon } from "../icons";
import ClinvarBadge from "../elements/ClinvarBadge";
import NotAvailable from "../elements/NotAvailable";
import SubpopBadge from "../elements/SubpopBadge";
import ClinvarExpanderDetail from "./ClinvarExpanderDetail";
import PhenotypeFilterPrompt from "./PhenotypeFilterPrompt";
import { useTooltip } from "../common/useTooltip";
import PopulationFrequencyTable from "./PopulationFrequencyTable";
import ResultsPanel from "./ResultsPanel";

/** The loading placeholder's height, roughly what a dozen rows of the loaded table take. */
export const VARIANTS_TABLE_MIN_HEIGHT = 431;

// Lower rank = sorts first (ascending) = more clinically concerning.
const PLOF_RANK = { HC: 0, LC: 1, none: 2 } as const;

const CLINVAR_SEVERITY_RANK: Record<ClinVarSignificance, number> = {
  Pathogenic: 0,
  "Likely pathogenic": 1,
  VUS: 2,
  "Likely benign": 3,
  Benign: 4,
};

type Tint = keyof typeof sourceTints;

// Height of the sticky group-header row, which the column-header row below has to sit exactly
// under. Fixed (rather than implied by padding/font-size) so there's no sub-pixel gap between them.
const GROUP_HEADER_HEIGHT = 28;

/**
 * Every data row is this tall: the height a two-line cell gives it (two 15px lines, a 2px gap and
 * the cell padding), so a row whose cells are all one line -- a variant that isn't in All of Us,
 * say -- doesn't come out shorter than its neighbours.
 */
const BODY_ROW_HEIGHT = 46;

/**
 * The columns that stay put while the rest scroll sideways: a row's identity, with its ClinVar
 * call, which an interpreter reads as part of what the variant is. Their group header ("pinned")
 * spans exactly these, so it can pin as one cell. The protein change rides under the consequence.
 */
const PINNED_COLUMN_IDS = ["expand", "variant", "gene", "consequence", "clinvar"] as const;
const PINNED_GROUP_ID = "pinned";
const LAST_PINNED_COLUMN_ID = PINNED_COLUMN_IDS[PINNED_COLUMN_IDS.length - 1];
/** The seam's hairline plus the width its shadow fades over. */
const SEAM_WIDTH = 9;

const styles = {
  headerRight: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  sub: {
    fontSize: 11,
    color: colors.textMuted,
  },
  // Every row is laid out and the page scrolls; only the horizontal axis scrolls here, since the
  // table is wider than a laptop window.
  tableScroll: {
    ...Style.table.scroller,
  },
  // separate (not collapse): under collapse, a sticky <th>'s border is painted via the table's
  // shared-grid-line model rather than as part of the cell's own box, and that desyncs from the
  // cell during scroll. borderSpacing: 0 keeps cells touching like collapse did.
  table: {
    ...Style.table.base,
    borderCollapse: "separate",
    borderSpacing: 0,
  },
  headerCell: {
    ...Style.table.headerCell,
    boxShadow: `inset 0 -1px 0 0 ${colors.border}`,
  },
  groupHeaderCell: {
    height: GROUP_HEADER_HEIGHT,
    boxShadow: "none",
    // Above the column-header row, which scrolls up underneath it.
    zIndex: 2,
    padding: "0 10px",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 0.2,
    textAlign: "center",
  },
  // The scope row's labels, "All participants" and "Phenotype-matched participants": small caps,
  // a step quieter than the source name above. The matched side is in primary ink with its count.
  scopeHeader: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    color: colors.textSecondary,
    fontSize: 10,
    fontWeight: 600,
    lineHeight: "15px",
    letterSpacing: 0.3,
    textTransform: "uppercase",
  },
  scopeHeaderMatched: {
    color: colors.textPrimary,
  },
  sourceHeaderCell: {
    color: colors.white,
    letterSpacing: 0.3,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 6,
  },
  // Pinned cells sit above the scrolling ones; pinned header cells above everything.
  pinnedCell: {
    position: "sticky",
    zIndex: 1,
  },
  pinnedHeaderCell: {
    zIndex: 3,
  },
  pinnedGroupHeaderCell: {
    zIndex: 4,
  },
  // The seam where pinned meets scrolling: a hairline, and, once the table is wide enough to
  // scroll, a soft shadow over the scrolling cells that reads as depth and says there is more
  // to the right. Each last-pinned cell draws it with this child, which spans the cell's exact
  // height, so the seam runs unbroken from one row into the next. It isn't a box-shadow on the
  // cell: a blurred shadow fades at the top and bottom of every cell, and down the table that
  // read as a row of dashes.
  seam: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: "100%",
    // Over the cell's own last pixel, so the hairline sits where the cell's border would.
    marginLeft: -1,
    width: 1,
    pointerEvents: "none",
    background: colors.border,
  },
  seamScrollable: {
    width: SEAM_WIDTH,
    background: `linear-gradient(to right, ${colors.border} 1px, ${alpha(colors.textPrimary, 0.12)} 1px, transparent)`,
  },
  // Within a source group the badge and the figures beside it read as one unit, so the gutter
  // between them is closed up: the badge cell gives up its right padding, the figures their left.
  // Badges and the globe above them centred together, so the header icon sits over the badges.
  badgeCell: {
    paddingRight: 2,
    textAlign: "center",
  },
  figuresCell: {
    paddingLeft: 6,
  },
  // The seam between the two scopes of the All of Us band: a rule a shade deeper than the tint,
  // down the left edge of the matched scope from its header through every row, so the cohort-wide
  // and matched figures read as two halves of one band rather than one run of columns.
  scopeRule: {
    borderLeft: `1px solid ${alpha(colors.textPrimary, 0.22)}`,
  },
  // The subpopulation columns' header, centred over the badges beneath it (see badgeCell).
  subpopHeader: {
    whiteSpace: "nowrap",
    cursor: "help",
  },
  // A two-line cell: the value that's compared across rows, then its supporting figure.
  stack: {
    display: "flex",
    flexDirection: "column",
    gap: 2,
    lineHeight: 1.25,
  },
  stackSecondary: {
    fontSize: 11,
    color: colors.textSecondary,
  },
  // The header stays one line, naming both lines of the cell beneath it.
  stackHeaderSecondary: {
    marginLeft: 4,
    fontWeight: 500,
    color: colors.textMuted,
  },
  matchedCount: {
    display: "inline-flex",
    alignItems: "center",
    gap: 3,
    color: colors.textSecondary,
    fontWeight: 600,
    fontVariantNumeric: "tabular-nums",
    lineHeight: "15px",
  },
  dataRow: {
    cursor: "pointer",
  },
  sourceMissing: {
    textAlign: "center",
  },
  // The one cell standing in for the whole matched block without a phenotype filter: it spans
  // every body row, so its prompt sits at the top in the matched tint.
  phenotypePrompt: {
    verticalAlign: "top",
    whiteSpace: "normal",
    padding: 0,
    background: sourceTints.matched.strong,
    cursor: "default",
  },
  cellNa: {
    color: colors.textMuted,
    fontStyle: "italic",
  },
  // A message spanning the scrolling columns, which can be wider than the window: it's centred in
  // its run, but stays within whatever part of the run is on screen, right of the pinned columns.
  cellNaSticky: {
    display: "inline-block",
    position: "sticky",
    right: 10,
  },
  plofBadge: {
    display: "inline-block",
    width: 28,
    textAlign: "center",
    padding: "0 4px",
    border: `1px solid ${colors.borderStrong}`,
    borderRadius: 4,
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: 600,
  },
  plofHc: {
    borderColor: colors.textPrimary,
    color: colors.textPrimary,
    fontWeight: 700,
  },
  plofNa: {
    color: colors.textMuted,
    cursor: "help",
  },
  // An expanded row and its detail read as one unit: they share the detail's fill, the rule
  // between them is dropped, and one accent bar runs down the left of both.
  expandedCell: {
    borderBottom: "1px solid transparent",
  },
  expandedRowFill: {
    background: colors.surface1,
  },
  expandedBar: {
    boxShadow: `inset 3px 0 0 ${colors.textAccent}`,
  },
  detailRow: {
    background: colors.surface1,
    padding: "0 12px 12px 13px",
    whiteSpace: "normal",
  },
  detailPanel: {
    display: "flex",
    flexDirection: "column",
    background: colors.surface2,
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    overflow: "hidden",
  },
  // The panel's body: ClinVar beside the population table.
  detailBody: {
    display: "grid",
    gridTemplateColumns: "318px 1fr",
  },
  // The panel's footer, holding the one thing to do from here: open the variant in Review. It
  // lives in the detail rather than at the end of the row, so the row stays figures only and the
  // action sits with the evidence it acts on.
  detailActions: {
    display: "flex",
    justifyContent: "flex-start",
    padding: "8px 12px",
    background: colors.surface1,
    borderTop: `1px solid ${colors.border}`,
  },
  detailClinvar: {
    padding: "12px 14px",
    borderRight: `1px solid ${colors.border}`,
  },
  detailPopulations: {
    overflowX: "auto",
  },
  detailEmpty: {
    display: "flex",
    alignItems: "flex-start",
    gap: 12,
    padding: "14px 16px",
  },
  detailEmptyIcon: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    width: 32,
    height: 32,
    borderRadius: "50%",
    background: colors.surface0,
    border: `1px solid ${colors.border}`,
    color: colors.textMuted,
  },
  detailEmptyTitle: {
    margin: "0 0 3px",
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: 600,
  },
  detailEmptyText: {
    maxWidth: 560,
    margin: 0,
    color: colors.textSecondary,
    fontSize: 12,
    lineHeight: 1.5,
  },
  detailEmptyLinks: {
    display: "flex",
    gap: 14,
    marginTop: 8,
  },
  detailEmptyLink: {
    color: colors.textAccent,
    fontSize: 12,
    fontWeight: 600,
    textDecoration: "none",
  },
} as const satisfies Record<string, CSSProperties>;

// Each source's frequency and its counts share one two-line cell: AF on the first line, AC / AN
// beneath in quieter ink. The frequency is what's compared across rows; the counts back it up.
const AOU_COLUMN_IDS = ["aouSubpop", "aouFreq"] as const;
const GNOMAD_COLUMN_IDS = ["gnomadSubpop", "gnomadFreq"] as const;
const ANNOTATION_COLUMN_IDS = ["spliceAi", "plof"] as const;
// The AF ratio isn't a column: Review states it with the interval behind it, which a bare ratio
// in a cell can't.
const MATCHED_COLUMN_IDS = ["matchedFreq", "homozygotes", "heterozygotes", "clinvarPlpInTrans"] as const;

const TINT_COLUMN_IDS: Record<Tint, Set<string>> = {
  aou: new Set(AOU_COLUMN_IDS),
  gnomad: new Set(GNOMAD_COLUMN_IDS),
  matched: new Set(MATCHED_COLUMN_IDS),
};

const BADGE_COLUMN_IDS = new Set(["aouSubpop", "gnomadSubpop"]);

// What each sortable column is called in its sort button's accessible name. Most headers are
// JSX (an icon, an info label, a two-line header), so the name can't be read off them, and a
// bare "Sort" on fourteen buttons would leave a screen-reader user guessing which column.
const SORT_LABELS: Record<string, string> = {
  variant: "Variant",
  gene: "Gene",
  consequence: "Consequence",
  aouSubpop: "All of Us subpopulation",
  aouFreq: "All of Us frequency",
  gnomadSubpop: "gnomAD subpopulation",
  gnomadFreq: "gnomAD frequency",
  matchedFreq: "Matched frequency",
  homozygotes: "Homozygotes",
  heterozygotes: "Heterozygotes",
  clinvarPlpInTrans: "P/LP in trans",
  clinvar: "ClinVar",
  spliceAi: "SpliceAI",
  plof: "pLOF",
};

function sortButtonLabel(columnId: string, direction: false | "asc" | "desc"): string {
  const column = SORT_LABELS[columnId] ?? columnId;
  if (direction === "asc") return `${column} sorted ascending; change sort`;
  if (direction === "desc") return `${column} sorted descending; change sort`;
  return `Sort ${column}`;
}
const FIGURES_COLUMN_IDS = new Set(["aouFreq", "gnomadFreq"]);

/**
 * The matched scope's header and its first column, which draw the rule that divides the two
 * scopes inside the All of Us band (styles.scopeRule). The source row above is left whole.
 */
const SCOPE_RULE_IDS = new Set(["matchedScope", "matchedFreq"]);

/** Tighter inner padding for a badge cell and the figures cell beside it, and the scope rule where it falls. */
function gutterStyle(columnId: string): CSSProperties | undefined {
  const rule = SCOPE_RULE_IDS.has(columnId) ? styles.scopeRule : undefined;
  if (BADGE_COLUMN_IDS.has(columnId)) return { ...styles.badgeCell, ...rule };
  if (FIGURES_COLUMN_IDS.has(columnId)) return { ...styles.figuresCell, ...rule };
  return rule;
}

const SOURCE_HEADER_IDS = new Set(["aou", "gnomad"]);

const GROUP_TINTS: Record<string, Tint> = {
  aou: "aou",
  allParticipants: "aou",
  matchedScope: "matched",
  gnomad: "gnomad",
  gnomadScope: "gnomad",
};

function headerTint(columnId: string): Tint | null {
  return GROUP_TINTS[columnId] ?? null;
}

/**
 * Which column group a column belongs to, and therefore which tint it gets. Only leaf columns
 * have these ids -- a group-row header cell carries its group's id, so the tint band starts at
 * the column-header row below it.
 */
function tintOf(columnId: string): Tint | null {
  if (TINT_COLUMN_IDS.aou.has(columnId)) return "aou";
  if (TINT_COLUMN_IDS.gnomad.has(columnId)) return "gnomad";
  if (TINT_COLUMN_IDS.matched.has(columnId)) return "matched";
  return null;
}

/**
 * A run of columns a variant has nothing for, drawn as one cell with a message rather than a row
 * of bare dashes. The cell spans whichever of the group's columns are currently shown, from the
 * first of them.
 */
interface MissingGroup {
  columnIds: Set<string>;
  message: ReactNode;
  /** Tooltip on the merged cell. */
  title?: string;
}

const NOT_IN_AOU = (
  <>
    Not observed in <AllOfUs />
  </>
);

const AOU_MISSING_GROUP: MissingGroup = { columnIds: TINT_COLUMN_IDS.aou, message: NOT_IN_AOU };
const GNOMAD_MISSING_GROUP: MissingGroup = { columnIds: TINT_COLUMN_IDS.gnomad, message: "Not observed in gnomAD" };
/** No matched-participant statistics for a variant All of Us does have. */
const MATCHED_MISSING_GROUP: MissingGroup = { columnIds: TINT_COLUMN_IDS.matched, message: "No matched statistics" };

// Everything after the Variant column. A variant that isn't in All of Us has no VAT row, so it
// has no annotations, no gnomAD data and no matched statistics either -- not because gnomAD lacks
// it, but because the VAT only covers variants All of Us has seen. One message across the row
// says so, rather than a "not observed in gnomAD" that may not be true.
/** Below this many rows the no-phenotype prompt takes its one-line layout, so it doesn't stretch them. */
const COMPACT_PROMPT_BELOW_ROWS = 4;

const UNANNOTATED_GROUP: MissingGroup = {
  columnIds: new Set([
    "gene",
    "consequence",
    "clinvar",
    ...AOU_COLUMN_IDS,
    ...GNOMAD_COLUMN_IDS,
    ...MATCHED_COLUMN_IDS,
    ...ANNOTATION_COLUMN_IDS,
  ]),
  message: NOT_IN_AOU,
  title:
    "Annotations and gnomAD frequencies come from the All of Us variant annotation table, which only includes variants observed in All of Us.",
};

// The chevron takes its colour from its cell, which the row loop sets to the accent while the
// row is hovered or expanded: the affordance is easy to miss at rest, so it brightens wherever
// the pointer is, not only when it's over the 16px button itself.
const EXPAND_TOOLTIP = "Expand for ClinVar detail and population frequencies";

function ExpandButton({ expanded, variant, onToggle }: { expanded: boolean; variant: string; onToggle: () => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  const tooltip = useTooltip(ref, expanded ? "Collapse" : EXPAND_TOOLTIP, "right");
  return (
    <Clickable
      ref={ref}
      style={{ ...Style.buttons.icon, color: "inherit" }}
      hoverStyle={Style.buttons.iconHover}
      aria-expanded={expanded}
      aria-controls={`variant-detail-${variant}`}
      aria-label={expanded ? "Collapse row for more detail" : "Expand row for more detail"}
      {...tooltip.anchorProps}
      onClick={(event) => {
        // The row this sits in toggles on click too.
        event.stopPropagation();
        onToggle();
      }}
    >
      <ChevronRightIcon
        size={16}
        className="transition-transform"
        style={expanded ? { transform: "rotate(90deg)" } : undefined}
      />
      {tooltip.bubble}
    </Clickable>
  );
}

/**
 * The subpopulation column's header. It carries the caveat for the whole source group: the badge
 * beneath names the subpopulation with the highest allele frequency, and the figures beside it
 * are that subpopulation's, not the whole cohort's. Sitting over the badge it describes, it costs
 * the group no width, where the same words in the group header above forced the columns wider.
 */
function SubpopHeader({ source }: { source: "aou" | "gnomad" }) {
  const name = source === "aou" ? "All of Us" : "gnomAD";
  const codes = source === "aou" ? AOU_SUBPOP_CODES : GNOMAD_SUBPOP_CODES;
  return (
    <span
      style={styles.subpopHeader}
      title={`The ${name} subpopulation (${codes.join(", ")}) with the highest allele frequency for this variant. The figures beside it are that subpopulation's, not the entire ${name} cohort's; expand the row for the whole cohort.`}
    >
      Max subpop
    </span>
  );
}

/** A frequency over its allele counts, the cell every source group shares. */
function FrequencyCell({ af, ac, an }: { af: number; ac: number; an: number }) {
  return (
    <span style={styles.stack}>
      <span title={exactAf(af)}>{formatAf(af)}</span>
      <span style={styles.stackSecondary}>{formatAcAn(ac, an)}</span>
    </span>
  );
}

function FrequencyHeader({ tooltip }: { tooltip?: ReactNode }) {
  const label = (
    <>
      AF<span style={styles.stackHeaderSecondary}>· AC / AN</span>
    </>
  );
  return tooltip ? <InfoLabel tooltip={tooltip}>{label}</InfoLabel> : <span>{label}</span>;
}

/** Every column's value for one row, in table order, for the TSV export. */
function rowToTsvValues(row: MergedVariantRow): string[] {
  const { cohort } = row;
  const stats = row.matched;
  const na = "n/a";
  const cohortValues = cohort.annotated
    ? [
        cohort.gene,
        cohort.consequence,
        cohort.proteinChange,
        cohort.aouSubpopulation ?? na,
        cohort.aouAf !== null ? cohort.aouAf.toFixed(6) : na,
        cohort.aouAc !== null ? String(cohort.aouAc) : na,
        cohort.aouAn !== null ? String(cohort.aouAn) : na,
        cohort.gnomadSubpopulation ?? na,
        cohort.gnomadAf !== null ? cohort.gnomadAf.toFixed(6) : na,
        cohort.gnomadAc !== null ? String(cohort.gnomadAc) : na,
        cohort.gnomadAn !== null ? String(cohort.gnomadAn) : na,
      ]
    : Array(11).fill(na);
  const annotationValues = cohort.annotated
    ? [
        cohort.clinvarSignificance ?? na,
        cohort.clinvarStars !== null ? String(cohort.clinvarStars) : na,
        String(cohort.spliceAi),
        cohort.plof ?? na,
      ]
    : Array(4).fill(na);
  const matchedValues = stats
    ? [
        String(stats.cohortAc),
        String(stats.cohortAn),
        stats.cohortAf.toFixed(4),
        String(stats.homozygotes),
        String(stats.heterozygotes),
        String(stats.clinvarPlpInTrans),
        `${stats.afRatio.toFixed(1)}x`,
      ]
    : Array(7).fill(na);
  return [row.variant, ...cohortValues, ...matchedValues, ...annotationValues];
}

const TSV_HEADER = [
  "variant",
  "gene",
  "consequence",
  "protein_change",
  "aou_max_subpop",
  "aou_max_subpop_af",
  "aou_max_subpop_ac",
  "aou_max_subpop_an",
  "gnomad_max_subpop",
  "gnomad_max_subpop_af",
  "gnomad_max_subpop_ac",
  "gnomad_max_subpop_an",
  "filtered_ac",
  "filtered_an",
  "filtered_af",
  "n_homalt",
  "n_het",
  "clinvar_plp_in_trans",
  "af_ratio",
  "clinvar_significance",
  "clinvar_stars",
  "spliceai",
  "plof",
];

function downloadTsv(filename: string, contents: string) {
  const blob = new Blob([contents], { type: "text/tab-separated-values" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

interface VariantsPanelProps {
  cohortVariants: CohortVariantRow[];
  filteredVariants: FilteredVariantRow[];
  /** Whether a phenotype filter matched anyone; without one the matched columns hold a prompt to add one. */
  hasPhenotypeFilter: boolean;
  participantCount: number;
  /** The picked conditions' names, for the matched header's tooltip; empty when none was picked. */
  phenotypes: string[];
  /** Opens Review on the given variant. */
  onReview?: (variant: string) => void;
  /** Opens the search editor, from the prompt the matched columns show without a phenotype filter. */
  onAddPhenotypeFilter?: () => void;
}

export default function VariantsPanel({
  cohortVariants,
  filteredVariants,
  hasPhenotypeFilter,
  participantCount,
  phenotypes,
  onReview,
  onAddPhenotypeFilter,
}: VariantsPanelProps) {
  const rows = useMemo(() => mergeVariantRows(cohortVariants, filteredVariants), [cohortVariants, filteredVariants]);
  const [expandedVariants, setExpandedVariants] = useState<Set<string>>(new Set());
  const [sorting, setSorting] = useState<SortingState>([]);
  const { hoveredKey: hoveredRow, hoverProps: rowHoverProps } = useHoveredKey<string>();
  const { hoveredKey: hoveredHeader, hoverProps: headerHoverProps } = useHoveredKey<string>();

  function toggleExpanded(variant: string) {
    setExpandedVariants((current) => {
      const next = new Set(current);
      if (next.has(variant)) {
        next.delete(variant);
      } else {
        next.add(variant);
      }
      return next;
    });
  }

  const columnHelper = useMemo(() => createColumnHelper<MergedVariantRow>(), []);

  const columns = useMemo(
    () => [
      columnHelper.group({
        id: PINNED_GROUP_ID,
        header: "",
        enableSorting: false,
        columns: columnHelper.columns([
          columnHelper.display({
            id: "expand",
            header: "",
            enableSorting: false,
            cell: ({ row }) => (
              <ExpandButton
                expanded={expandedVariants.has(row.original.variant)}
                variant={row.original.variant}
                onToggle={() => toggleExpanded(row.original.variant)}
              />
            ),
          }),
          columnHelper.accessor("variant", {
            header: "Variant",
            cell: (info) => <span style={Style.elements.mono}>{info.getValue()}</span>,
          }),
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.gene : undefined), {
            id: "gene",
            header: "Gene",
            cell: ({ row }) => (row.original.cohort.annotated ? row.original.cohort.gene : <NotAvailable />),
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.consequence : undefined), {
            id: "consequence",
            // The protein notation beneath the consequence is self-describing, so the header names
            // the sort key alone.
            header: "Consequence",
            cell: ({ row }) => {
              const { cohort } = row.original;
              if (!cohort.annotated) return <NotAvailable />;
              return (
                <span style={styles.stack}>
                  <span>{cohort.consequence}</span>
                  <span style={{ ...styles.stackSecondary, ...Style.elements.mono, fontSize: 11 }}>{cohort.proteinChange}</span>
                </span>
              );
            },
            sortUndefined: "last",
          }),
          columnHelper.accessor(
            (row) =>
              row.cohort.annotated && row.cohort.clinvarSignificance
                ? CLINVAR_SEVERITY_RANK[row.cohort.clinvarSignificance]
                : undefined,
            {
              id: "clinvar",
              header: "ClinVar",
              cell: ({ row }) => {
                const { cohort } = row.original;
                if (!cohort.annotated || !cohort.clinvarSignificance) return <NotAvailable />;
                return (
                  <ClinvarBadge
                    significance={cohort.clinvarSignificance}
                    stars={cohort.clinvarStars}
                    conflicts={cohort.clinvarHasConflicts}
                    href={clinvarSearchUrl(cohort.variant)}
                  />
                );
              },
              sortUndefined: "last",
            },
          ),
        ]),
      }),
      // One All of Us band over both scopes: the cohort-wide figures, then the matched figures
      // right beside them, so the comparison the table exists for sits in one tinted block.
      // gnomAD follows as a band of its own.
      columnHelper.group({
        id: "aou",
        header: () => <AllOfUs />,
        enableSorting: false,
        columns: [
      columnHelper.group({
        id: "allParticipants",
        header: () => <span style={styles.scopeHeader}>All participants</span>,
        enableSorting: false,
        columns: columnHelper.columns([
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.aouSubpopulation ?? undefined : undefined), {
            id: "aouSubpop",
            header: () => <SubpopHeader source="aou" />,
            cell: ({ row }) =>
              row.original.cohort.annotated && row.original.cohort.aouSubpopulation ? (
                <SubpopBadge subpopulation={row.original.cohort.aouSubpopulation} />
              ) : (
                <NotAvailable />
              ),
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.aouAf ?? undefined : undefined), {
            id: "aouFreq",
            header: () => <FrequencyHeader />,
            cell: ({ row }) => {
              const { cohort } = row.original;
              return cohort.annotated && cohort.aouAf !== null && cohort.aouAc !== null && cohort.aouAn !== null ? (
                <FrequencyCell af={cohort.aouAf} ac={cohort.aouAc} an={cohort.aouAn} />
              ) : (
                <NotAvailable />
              );
            },
            sortUndefined: "last",
          }),
        ]),
      }),
      columnHelper.group({
        id: "matchedScope",
        header: () => (
          <InfoLabel
            tooltip={
              hasPhenotypeFilter
                ? phenotypes.length > 1
                  ? `Statistics among the ${formatInt(participantCount)} participants recorded with ${describeAlternatives(phenotypes)}, beside the figures for all participants to their left.`
                  : `Statistics among the ${formatInt(participantCount)} participants matched by the phenotype filter (${phenotypes[0]}), beside the figures for all participants to their left.`
                : "Add a phenotype filter to see these statistics among only the participants who have it, beside the figures for all participants to their left."
            }
          >
            <span style={{ ...styles.scopeHeader, ...styles.scopeHeaderMatched }}>
              Phenotype-matched participants
              {hasPhenotypeFilter && (
                <span style={styles.matchedCount}>
                  <UserIcon size={11} aria-hidden="true" />
                  {formatInt(participantCount)}
                </span>
              )}
            </span>
          </InfoLabel>
        ),
        enableSorting: false,
        columns: columnHelper.columns([
          columnHelper.accessor((row) => row.matched?.cohortAf, {
            id: "matchedFreq",
            enableSorting: hasPhenotypeFilter,
            header: () => <FrequencyHeader tooltip="Allele frequency among phenotype-matched participants, over the allele count and number behind it." />,
            cell: ({ row }) => {
              const stats = row.original.matched;
              return stats ? <FrequencyCell af={stats.cohortAf} ac={stats.cohortAc} an={stats.cohortAn} /> : <NotAvailable />;
            },
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => row.matched?.homozygotes, {
            id: "homozygotes",
            enableSorting: hasPhenotypeFilter,
            header: () => <InfoLabel tooltip="Matched participants carrying two copies of this allele.">Hom</InfoLabel>,
            cell: ({ row }) => row.original.matched?.homozygotes ?? <NotAvailable />,
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => row.matched?.heterozygotes, {
            id: "heterozygotes",
            enableSorting: hasPhenotypeFilter,
            header: () => <InfoLabel tooltip="Matched participants carrying one copy of this allele.">Het</InfoLabel>,
            cell: ({ row }) => row.original.matched?.heterozygotes ?? <NotAvailable />,
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => row.matched?.clinvarPlpInTrans, {
            id: "clinvarPlpInTrans",
            enableSorting: hasPhenotypeFilter,
            header: () => (
              <InfoLabel tooltip="Count of phenotype-matched participants with a ClinVar Pathogenic/Likely Pathogenic variant in trans with this variant.">
                P/LP in trans
              </InfoLabel>
            ),
            cell: ({ row }) => row.original.matched?.clinvarPlpInTrans ?? <NotAvailable />,
            sortUndefined: "last",
          }),
        ]),
      }),
        ],
      }),
      columnHelper.group({
        id: "gnomad",
        header: "gnomAD",
        enableSorting: false,
        columns: [
      columnHelper.group({
        // A second level, so gnomAD's name sits in the source row level with All of Us, with
        // nothing to say in the scope row beneath.
        id: "gnomadScope",
        header: "",
        enableSorting: false,
        columns: columnHelper.columns([
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.gnomadSubpopulation ?? undefined : undefined), {
            id: "gnomadSubpop",
            header: () => <SubpopHeader source="gnomad" />,
            cell: ({ row }) =>
              row.original.cohort.annotated && row.original.cohort.gnomadSubpopulation ? (
                <SubpopBadge subpopulation={row.original.cohort.gnomadSubpopulation} />
              ) : (
                <NotAvailable />
              ),
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.gnomadAf ?? undefined : undefined), {
            id: "gnomadFreq",
            header: () => <FrequencyHeader />,
            cell: ({ row }) => {
              const { cohort } = row.original;
              return cohort.annotated && cohort.gnomadAf !== null && cohort.gnomadAc !== null && cohort.gnomadAn !== null ? (
                <FrequencyCell af={cohort.gnomadAf} ac={cohort.gnomadAc} an={cohort.gnomadAn} />
              ) : (
                <NotAvailable />
              );
            },
            sortUndefined: "last",
          }),
        ]),
      }),
        ],
      }),
      columnHelper.group({
        id: "annotations",
        header: "",
        enableSorting: false,
        columns: columnHelper.columns([
          columnHelper.accessor((row) => (row.cohort.annotated ? row.cohort.spliceAi : undefined), {
            id: "spliceAi",
            header: "SpliceAI",
            cell: ({ row }) => (row.original.cohort.annotated ? row.original.cohort.spliceAi : <NotAvailable />),
            sortUndefined: "last",
          }),
          columnHelper.accessor((row) => (row.cohort.annotated ? PLOF_RANK[row.cohort.plof ?? "none"] : undefined), {
            id: "plof",
            header: "pLOF",
            cell: ({ row }) => {
              const { cohort } = row.original;
              if (!cohort.annotated) return <NotAvailable />;
              if (cohort.plof === null) {
                return (
                  <span style={styles.plofNa} title="LOFTEE does not score this consequence type">
                    —
                  </span>
                );
              }
              return (
                <span style={{ ...styles.plofBadge, ...(cohort.plof === "HC" ? styles.plofHc : undefined) }}>
                  {cohort.plof}
                </span>
              );
            },
            sortUndefined: "last",
          }),
        ]),
      }),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columnHelper, expandedVariants, participantCount, phenotypes, hasPhenotypeFilter],
  );

  // Each pinned column sticks at the left edge plus the widths of the pinned columns before it.
  // Widths come from the rendered header cells, re-read whenever the table's shape could change.
  const tableRef = useRef<HTMLTableElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [pinnedOffsets, setPinnedOffsets] = useState<Record<string, number>>({});
  /** The pinned columns' total width: where the scrolling columns begin. */
  const [pinnedWidth, setPinnedWidth] = useState(0);
  /** Whether the table is wider than its panel, so the pinned columns have something to pin against. */
  const [scrollable, setScrollable] = useState(false);
  useLayoutEffect(() => {
    const measure = () => {
      const offsets: Record<string, number> = {};
      let left = 0;
      for (const id of PINNED_COLUMN_IDS) {
        offsets[id] = left;
        // The fractional width, not offsetWidth's rounded one: summing rounded widths leaves each
        // cell a fraction short of its neighbour, a hairline slit the scrolling content shows through.
        left += tableRef.current?.querySelector<HTMLElement>(`th[data-column-id="${id}"]`)?.getBoundingClientRect().width ?? 0;
      }
      setPinnedOffsets((current) =>
        PINNED_COLUMN_IDS.every((id) => current[id] === offsets[id]) ? current : offsets,
      );
      setPinnedWidth(left);
      const scroller = scrollerRef.current;
      setScrollable(scroller !== null && scroller.scrollWidth > scroller.clientWidth);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [rows, hasPhenotypeFilter, sorting]);

  const pinnedIds = new Set<string>(PINNED_COLUMN_IDS);
  /** Sticky positioning for a pinned column's cell, or nothing for the rest. */
  function pinnedStyle(columnId: string): CSSProperties | undefined {
    if (columnId === PINNED_GROUP_ID) return { ...styles.pinnedCell, ...styles.pinnedGroupHeaderCell, left: 0 };
    if (!pinnedIds.has(columnId)) return undefined;
    return { ...styles.pinnedCell, left: pinnedOffsets[columnId] ?? 0 };
  }

  /** The seam a last-pinned cell draws down its right edge; see styles.seam. */
  const seam = <span aria-hidden="true" style={{ ...styles.seam, ...(scrollable ? styles.seamScrollable : undefined) }} />;

  // Without a phenotype filter the matched block holds only the prompt to add one, so it moves to
  // the end, out of the way of the figures there are. Moving the whole block keeps its group
  // headers whole.
  const columnOrder = useMemo(() => {
    if (hasPhenotypeFilter) return [];
    // A column keyed by a field name takes that as its id; one missing from the order would land last.
    type Def = { id?: string; accessorKey?: string; columns?: readonly Def[] };
    const leafIds = (defs: readonly Def[]): string[] =>
      defs.flatMap((def) => (def.columns ? leafIds(def.columns) : [def.id ?? def.accessorKey ?? ""]));
    const ids = leafIds(columns as readonly Def[]);
    return [...ids.filter((id) => !TINT_COLUMN_IDS.matched.has(id)), ...ids.filter((id) => TINT_COLUMN_IDS.matched.has(id))];
  }, [columns, hasPhenotypeFilter]);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, columnOrder },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => row.variant,
  });

  function handleExport() {
    const lines = rows.map((row) => rowToTsvValues(row).join("\t"));
    downloadTsv("variant_results.tsv", [TSV_HEADER.join("\t"), ...lines].join("\n") + "\n");
  }

  const bodyRows = table.getRowModel().rows;
  // Without a phenotype filter the matched columns stay, as one cell running down the whole body
  // that asks for a phenotype. Every row, and every expanded detail beneath one, gives way to it.
  const leafColumnIds = table.getVisibleLeafColumns().map((column) => column.id);
  const inPromptBlock = (columnId: string) => !hasPhenotypeFilter && TINT_COLUMN_IDS.matched.has(columnId);
  const promptStart = leafColumnIds.findIndex(inPromptBlock);
  const promptSpan = leafColumnIds.filter(inPromptBlock).length;
  const promptRowSpan = bodyRows.length + bodyRows.filter((row) => expandedVariants.has(row.original.variant)).length;

  /** The tint a cell carries, which deepens into a band across whichever row is hovered. */
  function cellBackground(tint: Tint | null, hovered: boolean): string | undefined {
    if (tint) return hovered ? sourceTints[tint].hover : sourceTints[tint].strong;
    return hovered ? colors.surface1 : undefined;
  }

  return (
    <ResultsPanel
      title="Candidate variants"
      headerRight={
        <div style={styles.headerRight}>
          <span style={styles.sub}>Showing {rows.length} results</span>
          <Clickable style={Style.buttons.primary} hoverStyle={Style.buttons.primaryHover} onClick={handleExport}>
            Export TSV
          </Clickable>
        </div>
      }
    >
      <div ref={scrollerRef} style={styles.tableScroll}>
          <table ref={tableRef} style={styles.table}>
            <thead>
              {table.getHeaderGroups().map((headerGroup, depth, headerGroups) => {
                const isGroupRow = depth < headerGroups.length - 1;
                return (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      // A group header cell carries its group's id; the source groups' ids are
                      // tint names, and the matched scope takes the matched tint, so each band
                      // starts in its top-most header row.
                      const tint = tintOf(header.column.id) ?? headerTint(header.column.id);
                      const isSourceHeader = depth === 0 && tint !== null && SOURCE_HEADER_IDS.has(header.column.id);
                      const sortable = header.column.getCanSort();
                      const sortDirection = header.column.getIsSorted();
                      return (
                        <th
                          key={header.id}
                          colSpan={header.colSpan}
                          data-column-id={header.column.id}
                          // Only on the sorted header: ARIA asks for aria-sort on one header at a
                          // time, and the sort buttons already say which other columns can sort.
                          aria-sort={sortDirection === "asc" ? "ascending" : sortDirection === "desc" ? "descending" : undefined}
                          style={{
                            ...styles.headerCell,
                            ...(isGroupRow ? styles.groupHeaderCell : undefined),
                            top: depth * GROUP_HEADER_HEIGHT,
                            ...gutterStyle(header.column.id),
                            background: cellBackground(tint, false) ?? styles.headerCell.background,
                            ...(isSourceHeader ? { ...styles.sourceHeaderCell, background: sourceTints[tint].header } : undefined),
                            ...(sortable ? Style.table.sortable : undefined),
                            ...(sortable && hoveredHeader === header.id ? Style.table.sortableHover : undefined),
                            ...pinnedStyle(header.column.id),
                            ...(pinnedIds.has(header.column.id) ? styles.pinnedHeaderCell : undefined),
                          }}
                          onClick={sortable ? header.column.getToggleSortingHandler() : undefined}
                          {...(sortable ? headerHoverProps(header.id) : undefined)}
                        >
                          {(header.column.id === PINNED_GROUP_ID || header.column.id === LAST_PINNED_COLUMN_ID) && seam}
                          {header.isPlaceholder ? null : (
                            <>
                              {flexRender(header.column.columnDef.header, header.getContext())}
                              {sortable && (
                                // The whole header cell sorts on click for mouse users; this button
                                // is the keyboard path and the visible affordance. It sits beside the
                                // label rather than around it because some labels hold an info button
                                // of their own.
                                <button
                                  type="button"
                                  style={{
                                    ...Style.table.sortButton,
                                    ...(sortDirection ? Style.table.sortButtonActive : undefined),
                                  }}
                                  // Which direction comes first depends on the column (numbers sort
                                  // descending first), so the label names the state, not the next step.
                                  aria-label={sortButtonLabel(header.column.id, sortDirection)}
                                  onClick={(event) => {
                                    // The header cell's own click would toggle it a second time.
                                    event.stopPropagation();
                                    header.column.toggleSorting();
                                  }}
                                >
                                  <SortIcon direction={sortDirection || "none"} size={11} aria-hidden="true" />
                                </button>
                              )}
                            </>
                          )}
                        </th>
                      );
                    })}
                  </tr>
                );
              })}
            </thead>
            <tbody>
              {bodyRows.map((row, rowIndex) => {
                const { cohort } = row.original;
                // A source with no data for this variant collapses its whole column group into one
                // "not observed" cell, rather than a row of bare dashes.
                const missingGroups: MissingGroup[] = !cohort.annotated
                  ? [UNANNOTATED_GROUP]
                  : [
                      cohort.aouSubpopulation === null ? AOU_MISSING_GROUP : null,
                      cohort.gnomadSubpopulation === null ? GNOMAD_MISSING_GROUP : null,
                      hasPhenotypeFilter && !row.original.matched ? MATCHED_MISSING_GROUP : null,
                    ].filter((group) => group !== null);
                const hovered = hoveredRow === row.id;
                const expanded = expandedVariants.has(row.original.variant);
                const visibleCells = row.getVisibleCells();
                return (
                  <Fragment key={row.id}>
                    <tr
                      data-variant-row
                      style={styles.dataRow}
                      onClick={() => toggleExpanded(row.original.variant)}
                      {...rowHoverProps(row.id)}
                    >
                      {visibleCells.map((cell, index) => {
                        if (inPromptBlock(cell.column.id)) {
                          if (rowIndex !== 0 || index !== promptStart) return null;
                          return (
                            <td
                              key="phenotype-prompt"
                              colSpan={promptSpan}
                              rowSpan={promptRowSpan}
                              style={styles.phenotypePrompt}
                              data-testid="phenotype-prompt-cell"
                              // The cell belongs to the first row but runs down all of them, so it
                              // neither expands that row nor bands it while the pointer is inside.
                              onClick={(event) => event.stopPropagation()}
                              onMouseEnter={rowHoverProps(row.id).onMouseLeave}
                              onMouseLeave={rowHoverProps(row.id).onMouseEnter}
                            >
                              <PhenotypeFilterPrompt
                                phenotypes={phenotypes}
                                compact={bodyRows.length < COMPACT_PROMPT_BELOW_ROWS}
                                onAddPhenotypeFilter={onAddPhenotypeFilter}
                              />
                            </td>
                          );
                        }
                        const tint = tintOf(cell.column.id);
                        const pinned = pinnedIds.has(cell.column.id);
                        const cellStyle: CSSProperties = {
                          ...Style.table.bodyCell,
                          height: BODY_ROW_HEIGHT,
                          ...gutterStyle(cell.column.id),
                          ...(expanded ? styles.expandedCell : undefined),
                          background:
                            cellBackground(tint, hovered) ??
                            (expanded ? styles.expandedRowFill.background : pinned ? colors.surface2 : undefined),
                          ...(expanded && index === 0 ? styles.expandedBar : undefined),
                          // See ExpandButton: the chevron inherits this.
                          ...(cell.column.id === "expand"
                            ? { color: hovered || expanded ? colors.textAccent : colors.textSecondary }
                            : undefined),
                        };
                        const group = missingGroups.find((candidate) => candidate.columnIds.has(cell.column.id));
                        if (group) {
                          // A group is drawn as runs of adjacent cells rather than one cell: the
                          // prompt block can split it, and a run never crosses from the pinned
                          // columns into the scrolling ones, so the pinned part stays put and
                          // draws the seam like any other row. The message goes in the first
                          // scrolling run, beside the other rows' figures.
                          const inRun = (id: string) =>
                            group.columnIds.has(id) && !inPromptBlock(id) && pinnedIds.has(id) === pinned;
                          if (index > 0 && inRun(visibleCells[index - 1].column.id)) return null;
                          let end = index;
                          while (end < visibleCells.length && inRun(visibleCells[end].column.id)) end++;
                          const runCells = visibleCells.slice(index, end);
                          const holdsMessage =
                            !pinned &&
                            !visibleCells
                              .slice(0, index)
                              .some((candidate) => group.columnIds.has(candidate.column.id) && !pinnedIds.has(candidate.column.id));
                          const endsPinned = runCells[runCells.length - 1].column.id === LAST_PINNED_COLUMN_ID;
                          // A run keeps its source's tint only if it lies within one source; the
                          // run across everything for a variant not in All of Us is untinted.
                          const runTint = runCells.every((candidate) => tintOf(candidate.column.id) === tint) ? tint : null;
                          return (
                            <td
                              key={cell.id}
                              colSpan={runCells.length}
                              style={{
                                ...cellStyle,
                                ...styles.sourceMissing,
                                background: cellBackground(runTint, hovered) ?? (pinned ? colors.surface2 : undefined),
                                ...pinnedStyle(cell.column.id),
                              }}
                              title={group.title}
                            >
                              {endsPinned && seam}
                              {holdsMessage && (
                                <span style={{ ...styles.cellNa, ...styles.cellNaSticky, left: pinnedWidth + 10 }}>{group.message}</span>
                              )}
                            </td>
                          );
                        }
                        return (
                          <td key={cell.id} style={{ ...cellStyle, ...pinnedStyle(cell.column.id) }}>
                            {cell.column.id === LAST_PINNED_COLUMN_ID && seam}
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        );
                      })}
                    </tr>
                    {expanded && (
                      <tr id={`variant-detail-${row.original.variant}`}>
                        <td
                          colSpan={promptSpan ? promptStart : visibleCells.length}
                          style={{ ...Style.table.bodyCell, ...styles.detailRow, ...styles.expandedBar }}
                        >
                          <div style={styles.detailPanel}>
                          {cohort.annotated ? (
                            <div style={styles.detailBody}>
                              <div style={styles.detailClinvar}>
                                <ClinvarExpanderDetail variant={cohort} />
                              </div>
                              <div style={styles.detailPopulations}>
                                <PopulationFrequencyTable variant={cohort} />
                              </div>
                            </div>
                          ) : (
                            <div style={{ ...styles.detailBody, gridTemplateColumns: "1fr" }}>
                              <div style={styles.detailEmpty}>
                                <span style={styles.detailEmptyIcon} aria-hidden="true">
                                  <EyeOffIcon size={16} />
                                </span>
                                <div>
                                  <p style={styles.detailEmptyTitle}>
                                    Not observed in <AllOfUs />
                                  </p>
                                  <p style={styles.detailEmptyText}>
                                    VIA only shows annotations and frequencies for variants found in <AllOfUs />,
                                    so there's nothing to show here. This variant may still be in gnomAD or ClinVar.
                                  </p>
                                  <div style={styles.detailEmptyLinks}>
                                    {[
                                      { label: "Look up in gnomAD ↗", href: gnomadVariantUrl(row.original.variant) },
                                      { label: "Look up in ClinVar ↗", href: clinvarSearchUrl(row.original.variant) },
                                    ].map(({ label, href }) => (
                                      <a
                                        key={href}
                                        style={styles.detailEmptyLink}
                                        href={href}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        onClick={(event) => event.stopPropagation()}
                                      >
                                        {label}
                                      </a>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}
                          {onReview && (
                            <div style={styles.detailActions}>
                              <Clickable
                                style={Style.buttons.accent}
                                hoverStyle={Style.buttons.accentHover}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  onReview(row.original.variant);
                                }}
                                title="Open Review on this variant"
                              >
                                <CompareIcon size={14} aria-hidden="true" />
                                Review this variant
                              </Clickable>
                            </div>
                          )}
                          </div>
                        </td>
                        {/* The prompt cell runs through this row; the columns after it close it out. */}
                        {promptSpan > 0 && promptStart + promptSpan < visibleCells.length && (
                          <td
                            colSpan={visibleCells.length - promptStart - promptSpan}
                            style={{ ...Style.table.bodyCell, ...styles.detailRow }}
                          />
                        )}
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
      </div>
    </ResultsPanel>
  );
}
