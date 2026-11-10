import type { CSSProperties } from "react";
import colors, { alpha, POPMAX_BACKGROUND, sourceTints } from "../../libs/colors";
import { useHover, useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import type { AnnotatedCohortVariant, GnomadSubpopCode, PopulationFrequency, SubpopCode } from "../../types/results";
import { exactAf, formatAcAn, formatAf, formatInt } from "../../utils/format";
import { SUBPOP_COLOR, SUBPOP_LABEL } from "../../utils/subpopulations";
import AllOfUs from "../common/AllOfUs";
import NotAvailable from "../elements/NotAvailable";
import { gnomadVariantUrl } from "../../utils/externalLinks";

// The union of both sources' subpopulation vocabularies, alphabetical by code -- a stable order
// so rows line up across variants. AoU has EUR/MID with no gnomAD equivalent; gnomAD has
// ASJ/FIN/NFE with no AoU equivalent, so a population absent from one source's own vocabulary
// (not just absent from this variant) renders as an em dash too, same as missing data.
const ALL_POPULATION_CODES: (SubpopCode | GnomadSubpopCode)[] = [
  "AFR",
  "AMR",
  "ASJ",
  "EAS",
  "EUR",
  "FIN",
  "MID",
  "NFE",
  "OTH",
  "SAS",
];

// Identifies the summary row at the bottom for hover tracking; not a population code.
const ALL_POPULATIONS_ROW = "all";

type Source = "aou" | "gnomad";

const styles = {
  table: {
    ...Style.table.base,
    borderCollapse: "collapse",
  },
  cell: {
    padding: "1px 10px",
    textAlign: "left",
  },
  populationHeader: {
    color: colors.textSecondary,
    fontWeight: 600,
    verticalAlign: "bottom",
  },
  groupHeader: {
    paddingTop: 11,
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 0.2,
    textAlign: "center",
  },
  populationLabel: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    verticalAlign: "top",
  },
  allPopulationsLabel: {
    color: colors.textMuted,
  },
  // Three kinds of "no number", kept apart: a population the source doesn't report at all (not
  // covered), a variant the source has no record of (not observed), and a covered population
  // where the variant simply has no carriers (a real 0, in muted ink).
  notCovered: {
    color: colors.textMuted,
    fontSize: 11,
    fontStyle: "italic",
    textAlign: "center",
    cursor: "help",
  },
  notObserved: {
    color: colors.textMuted,
    fontStyle: "italic",
    textAlign: "center",
    verticalAlign: "middle",
  },
  zeroCarriers: {
    color: colors.textMuted,
  },
  bottomSpacer: {
    height: 12,
    padding: 0,
  },
  sourceLink: {
    color: "inherit",
    fontWeight: 600,
    textDecoration: "none",
  },
  maxValue: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
  },
  maxValueText: Style.elements.trimmedText,
  maxMarker: {
    ...Style.elements.trimmedText,
    padding: "2px 5px",
    borderRadius: 4,
    background: colors.brandNavy,
    color: colors.white,
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: "0.04em",
  },
} as const satisfies Record<string, CSSProperties>;

/** AoU columns lean accent-blue, gnomAD columns stay neutral. */
const SOURCE_INK: Record<Source, string> = {
  aou: colors.textAccent,
  gnomad: colors.textSecondary,
};

function sourceCellStyle(source: Source, hovered: boolean): CSSProperties {
  return {
    ...styles.cell,
    background: hovered ? sourceTints[source].hover : sourceTints[source].soft,
    color: SOURCE_INK[source],
  };
}

const SOURCE_NAME: Record<Source, string> = {
  aou: "All of Us",
  gnomad: "gnomAD",
};

/** Faint diagonal hatching over a cell's fill, for a population the source doesn't cover. */
function hatched(fill: string): string {
  const line = alpha(colors.textMuted, 0.14);
  return `repeating-linear-gradient(135deg, transparent 0 4px, ${line} 4px 5px), ${fill}`;
}

function byPopulation(frequencies: PopulationFrequency[]): Map<string, PopulationFrequency> {
  return new Map(frequencies.map((frequency) => [frequency.population, frequency]));
}

interface FrequencyCellsProps {
  af: number | null | undefined;
  ac: number | null | undefined;
  an: number | null | undefined;
  /** Whether the source reports this population at all. */
  covered: boolean;
  /** Names the population in the not-covered tooltip. */
  populationLabel: string;
  isMax: boolean;
  source: Source;
  hovered: boolean;
}

function FrequencyCells({ af, ac, an, covered, populationLabel, isMax, source, hovered }: FrequencyCellsProps) {
  const cellStyle = sourceCellStyle(source, hovered);

  if (!covered) {
    return (
      <td
        colSpan={2}
        style={{ ...cellStyle, ...styles.notCovered, background: hatched(String(cellStyle.background)) }}
        title={`${SOURCE_NAME[source]} doesn't report a ${populationLabel} population.`}
      >
        Not an inferred ancestry category
      </td>
    );
  }

  if (af == null || ac == null || an == null) {
    return (
      <>
        <td style={cellStyle}>
          <NotAvailable />
        </td>
        <td style={cellStyle}>
          <NotAvailable />
        </td>
      </>
    );
  }

  if (ac === 0) {
    const zeroStyle = { ...cellStyle, ...styles.zeroCarriers };
    const title = `No carriers among ${formatInt(an)} alleles sampled in ${SOURCE_NAME[source]}.`;
    return (
      <>
        <td style={zeroStyle} title={title}>
          {formatAf(af)}
        </td>
        <td style={zeroStyle} title={title}>
          {formatAcAn(ac, an)}
        </td>
      </>
    );
  }

  // The max cell keeps its highlight ink even while hovered, but gives up its own fill to the
  // hover band so the row still reads as one.
  const valueStyle: CSSProperties = isMax
    ? {
        ...cellStyle,
        background: hovered ? cellStyle.background : POPMAX_BACKGROUND,
        color: colors.textPrimary,
        fontWeight: 600,
      }
    : cellStyle;

  return (
    <>
      <td style={valueStyle}>
        {isMax ? (
          <span style={styles.maxValue}>
            <span style={styles.maxValueText} title={exactAf(af)}>
              {formatAf(af)}
            </span>
            <span style={styles.maxMarker}>MAX</span>
          </span>
        ) : (
          <span title={exactAf(af)}>{formatAf(af)}</span>
        )}
      </td>
      <td style={valueStyle}>{formatAcAn(ac, an)}</td>
    </>
  );
}

interface PopulationFrequencyTableProps {
  variant: AnnotatedCohortVariant;
}

export default function PopulationFrequencyTable({ variant }: PopulationFrequencyTableProps) {
  const { hoveredKey: hoveredRow, hoverProps: rowHoverProps } = useHoveredKey<string>();
  const { hovered: linkHovered, hoverProps: linkHoverProps } = useHover();

  const aouByPopulation = byPopulation(variant.aouPopulations);
  const gnomadByPopulation = byPopulation(variant.gnomadPopulations);
  // A source lists every population it covers, with nulls throughout when it has no record of
  // this variant -- in which case its columns become one "not observed" block, as in the cohort
  // table, rather than a column of dashes that reads the same as "not covered".
  const notObserved: Record<Source, boolean> = {
    aou: variant.aouAllAc == null && variant.aouPopulations.every((p) => p.ac == null),
    gnomad: variant.gnomadAllAc == null && variant.gnomadPopulations.every((p) => p.ac == null),
  };
  // Every population row plus "All populations".
  const bodyRowCount = ALL_POPULATION_CODES.length + 1;

  function notObservedBlock(source: Source, firstRow: boolean) {
    if (!firstRow) return null;
    return (
      <td colSpan={2} rowSpan={bodyRowCount} style={{ ...sourceCellStyle(source, false), ...styles.notObserved }}>
        Not observed in {source === "aou" ? <AllOfUs /> : SOURCE_NAME[source]}
      </td>
    );
  }

  function headerStyle(source: Source): CSSProperties {
    return { ...sourceCellStyle(source, false), fontWeight: 600 };
  }

  function groupHeaderStyle(source: Source): CSSProperties {
    return { ...sourceCellStyle(source, false), ...styles.groupHeader };
  }

  function labelCellStyle(hovered: boolean): CSSProperties {
    return { ...styles.cell, ...(hovered ? { background: colors.surface1 } : undefined) };
  }

  return (
    <table style={styles.table}>
      <thead>
        <tr>
          <th rowSpan={2} style={{ ...styles.cell, ...styles.populationHeader }}>
            Population
          </th>
          <th colSpan={2} style={groupHeaderStyle("aou")}>
            <AllOfUs />
          </th>
          <th colSpan={2} style={groupHeaderStyle("gnomad")}>
            gnomAD{" "}
            {variant.gnomadSubpopulation !== null && (
              <a
                style={{ ...styles.sourceLink, ...(linkHovered ? { color: colors.textAccent } : undefined) }}
                href={gnomadVariantUrl(variant.variant)}
                target="_blank"
                rel="noopener noreferrer"
                title={`Open ${variant.variant} in gnomAD`}
                aria-label={`Open ${variant.variant} in gnomAD (opens in new tab)`}
                onClick={(event) => event.stopPropagation()}
                {...linkHoverProps}
              >
                ↗
              </a>
            )}
          </th>
        </tr>
        <tr>
          <th style={headerStyle("aou")}>AF</th>
          <th style={headerStyle("aou")}>AC / AN</th>
          <th style={headerStyle("gnomad")}>AF</th>
          <th style={headerStyle("gnomad")}>AC / AN</th>
        </tr>
      </thead>
      <tbody>
        {ALL_POPULATION_CODES.map((population, rowIndex) => {
          const hovered = hoveredRow === population;
          return (
            <tr key={population} {...rowHoverProps(population)}>
              <td style={labelCellStyle(hovered)}>
                <span style={styles.populationLabel}>
                  <span style={Style.colorDot(SUBPOP_COLOR[population])} />
                  {SUBPOP_LABEL[population]}
                </span>
              </td>
              {notObserved.aou ? (
                notObservedBlock("aou", rowIndex === 0)
              ) : (
                <FrequencyCells
                  af={aouByPopulation.get(population)?.af}
                  ac={aouByPopulation.get(population)?.ac}
                  an={aouByPopulation.get(population)?.an}
                  covered={aouByPopulation.has(population)}
                  populationLabel={SUBPOP_LABEL[population]}
                  isMax={variant.aouSubpopulation === population}
                  source="aou"
                  hovered={hovered}
                />
              )}
              {notObserved.gnomad ? (
                notObservedBlock("gnomad", rowIndex === 0)
              ) : (
                <FrequencyCells
                  af={gnomadByPopulation.get(population)?.af}
                  ac={gnomadByPopulation.get(population)?.ac}
                  an={gnomadByPopulation.get(population)?.an}
                  covered={gnomadByPopulation.has(population)}
                  populationLabel={SUBPOP_LABEL[population]}
                  isMax={variant.gnomadSubpopulation === population}
                  source="gnomad"
                  hovered={hovered}
                />
              )}
            </tr>
          );
        })}
        <tr {...rowHoverProps(ALL_POPULATIONS_ROW)}>
          <td
            style={{
              ...labelCellStyle(hoveredRow === ALL_POPULATIONS_ROW),
              ...styles.allPopulationsLabel,
            }}
          >
            All populations
          </td>
          {!notObserved.aou && (
            <FrequencyCells
              af={variant.aouAllAf}
              ac={variant.aouAllAc}
              an={variant.aouAllAn}
              covered
              populationLabel="combined"
              isMax={false}
              source="aou"
              hovered={hoveredRow === ALL_POPULATIONS_ROW}
            />
          )}
          {!notObserved.gnomad && (
            <FrequencyCells
              af={variant.gnomadAllAf}
              ac={variant.gnomadAllAc}
              an={variant.gnomadAllAn}
              covered
              populationLabel="combined"
              isMax={false}
              source="gnomad"
              hovered={hoveredRow === ALL_POPULATIONS_ROW}
            />
          )}
        </tr>
        <tr aria-hidden="true">
          <td style={styles.bottomSpacer} />
          {(["aou", "aou", "gnomad", "gnomad"] as const).map((source, index) => (
            <td key={index} style={{ ...sourceCellStyle(source, false), ...styles.bottomSpacer }} />
          ))}
        </tr>
        <tr aria-hidden="true">
          <td style={styles.bottomSpacer} />
          {(["aou", "aou", "gnomad", "gnomad"] as const).map((source, index) => (
            <td key={index} style={{ ...sourceCellStyle(source, false), ...styles.bottomSpacer }} />
          ))}
        </tr>
      </tbody>
    </table>
  );
}
