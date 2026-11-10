import type { CSSProperties, ReactNode } from "react";
import colors, { POPMAX_BACKGROUND } from "../../libs/colors";
import { useMediaQuery } from "../../libs/hooks";
import * as Style from "../../libs/style";
import type { BreakdownSegment } from "../../types/results";
import { ancestryContext, largestMatchedAncestry, type ComparisonRow } from "../../utils/comparison";
import { clinvarSearchUrl } from "../../utils/externalLinks";
import { describeAlternatives } from "../../utils/phenotypes";
import {
  exactAf,
  formatAcAn,
  formatAf,
  formatExpected,
  formatInt,
  formatInterval,
  formatPValue,
  formatRatio,
  formatSig,
} from "../../utils/format";
import { MIN_ALLELES_FOR_ENRICHMENT, SIMILARITY_FOLD } from "../../utils/statistics";
import { SUBPOP_COLOR, SUBPOP_LABEL } from "../../utils/subpopulations";
import AllOfUs from "../common/AllOfUs";
import InfoLabel from "../common/InfoLabel";
import InfoTooltip from "../common/InfoTooltip";
import ClinvarBadge from "../elements/ClinvarBadge";
import NotAvailable from "../elements/NotAvailable";
import VerdictGlyph from "./VerdictGlyph";
import { verdictTone } from "./verdictTone";

// Below this the two tables no longer fit beside each other and stack instead.
const STACKED_QUERY = "(max-width: 1000px)";

// Every section shares one rhythm: an eyebrow title, then its content, 24px apart. The two tables
// sit side by side so the whole view fits the window's height without scrolling.
const styles = {
  root: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  // Each column is title then table, so the two tables' top edges line up.
  columns: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    gap: 32,
    alignItems: "start",
  },
  // Identity on the left, annotation facts on the right, both two lines tall so they share a
  // rhythm: the name line over the description line, and each fact's label over its value.
  identity: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px 24px",
  },
  identityText: {
    display: "flex",
    flexDirection: "column",
    gap: 3,
    minWidth: 0,
  },
  // Two lines in two voices. The name line is how a clinician says the variant ("LDLR
  // p.Cys681Ter"): the gene and its protein change together, in primary ink. The description
  // line holds the supporting facts, the consequence category and the genomic coordinate, in
  // secondary. Neither wraps: a long protein change truncates, with the full text in its title.
  // Both lines have fixed heights: baseline-aligning two type sizes makes a flex row a few pixels
  // taller than its line-height, so without them the header grew whenever a variant had a
  // protein change, and stepping through variants jogged everything below it.
  nameLine: {
    display: "flex",
    alignItems: "baseline",
    gap: 10,
    minWidth: 0,
    height: 26,
    lineHeight: "26px",
    color: colors.textPrimary,
  },
  gene: {
    fontSize: 20,
    fontWeight: 700,
    flexShrink: 0,
  },
  proteinChange: {
    ...Style.elements.mono,
    fontSize: 16,
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  descriptionLine: {
    display: "flex",
    alignItems: "baseline",
    gap: 6,
    height: 18,
    lineHeight: "18px",
    fontSize: 12.5,
    color: colors.textSecondary,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  variantId: {
    ...Style.elements.mono,
  },
  // The variant's annotations as labelled facts, like the blocks of the summary strip.
  facts: {
    display: "flex",
    alignItems: "stretch",
    margin: 0,
  },
  fact: {
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    gap: 6,
    padding: "0 16px",
    borderLeft: `1px solid ${colors.border}`,
  },
  factFirst: {
    paddingLeft: 0,
    borderLeft: "none",
  },
  factValue: {
    display: "flex",
    alignItems: "center",
    height: 20,
    fontSize: 13,
    fontWeight: 600,
    color: colors.textPrimary,
    fontVariantNumeric: "tabular-nums",
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  sectionTitle: {
    ...Style.elements.eyebrow,
    display: "flex",
    alignItems: "center",
    gap: 2,
  },
  // A soft, borderless tint, like a large version of a status pill: the colour and the glyph carry
  // the verdict, so no outline is needed to set it apart.
  verdict: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    padding: "14px 18px",
    borderRadius: 12,
  },
  // Fixed heights, so the strip is the same height whatever the verdict: with or without a ratio,
  // and with a one- or two-line sentence. Centered rather than baseline-aligned, since the mono
  // ratio's baseline sits lower than the sans word's.
  verdictLine: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "4px 10px",
    height: 24,
  },
  verdictWord: {
    fontSize: 17,
    fontWeight: 700,
    lineHeight: "22px",
  },
  // Set like the evidence figures: sans with tabular digits, a little lighter than the word.
  verdictRatio: {
    fontSize: 17,
    fontWeight: 600,
    lineHeight: "22px",
    fontVariantNumeric: "tabular-nums",
    opacity: 0.85,
  },
  // Indented to start under the word, past the glyph.
  verdictSentence: {
    margin: "0 0 0 34px",
    fontSize: 12.5,
    lineHeight: "19px",
    minHeight: 38,
    color: colors.textBody,
  },
  // Evidence: a row of stat tiles, each a label over a headline figure over a short reading of it.
  evidence: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    gap: 10,
  },
  tile: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    padding: 12,
    border: `1px solid ${colors.border}`,
    borderRadius: Style.radius,
    background: colors.surface1,
  },
  // The figure is the tile's point, so it's set large, in the sans face with lining tabular digits.
  tileValue: {
    fontSize: 22,
    fontWeight: 700,
    lineHeight: "28px",
    color: colors.textPrimary,
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  // The words joining two figures ("vs", "of"), a step back so the numbers read first.
  tileConnective: {
    fontSize: 13,
    fontWeight: 500,
    color: colors.textMuted,
  },
  // Two lines, held open whether the note needs them or not, so every tile is the same height.
  tileNote: {
    fontSize: 11,
    lineHeight: "15px",
    minHeight: 30,
    color: colors.textSecondary,
  },
  // Head to head and ancestry share one table treatment.
  table: {
    ...Style.table.base,
    borderCollapse: "collapse",
    tableLayout: "fixed",
  },
  th: {
    padding: "7px 10px",
    background: colors.surface1,
    borderBottom: `1px solid ${colors.border}`,
    color: colors.textSecondary,
    fontSize: 11,
    fontWeight: 600,
    textAlign: "left",
    verticalAlign: "bottom",
    whiteSpace: "nowrap",
  },
  td: {
    padding: "6px 10px",
    borderBottom: `1px solid ${colors.border}`,
    verticalAlign: "middle",
  },
  metric: {
    color: colors.textSecondary,
    fontSize: 11.5,
    whiteSpace: "nowrap",
  },
  value: {
    ...Style.elements.mono,
    fontSize: 11.5,
    color: colors.textBody,
  },
  valueStrong: {
    fontSize: 15,
    fontWeight: 700,
    color: colors.textPrimary,
  },
  populationLabel: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    fontSize: 12,
    color: colors.textBody,
  },
  shareBar: {
    display: "inline-block",
    height: 6,
    borderRadius: 3,
    marginRight: 6,
    verticalAlign: "middle",
    background: colors.textAccent,
  },
  empty: {
    padding: "18px 12px",
    borderRadius: Style.radius,
    background: colors.surface1,
    textAlign: "center",
    color: colors.textSecondary,
    fontSize: 12.5,
    lineHeight: 1.5,
  },
} as const satisfies Record<string, CSSProperties>;

interface ReviewDetailProps {
  row: ComparisonRow;
  /** The picked conditions' names; the matched participants have any of them. */
  phenotypes: string[];
  participantCount: number;
  ancestryBreakdown: BreakdownSegment[];
  /** How many candidates actually ran a test, for the Bonferroni note on the p-value. */
  candidateCount: number;
}

export default function ReviewDetail({
  row,
  phenotypes,
  participantCount,
  ancestryBreakdown,
  candidateCount,
}: ReviewDetailProps) {
  const { cohort, matched, enrichment } = row;
  const tone = verdictTone(enrichment);
  const allAncestry = ancestryContext(cohort, ancestryBreakdown);
  // A group with no matched participants and no frequency in either source would be a row of
  // dashes, so it's left out; the ones that remain are the ones that bear on the verdict.
  const ancestry = allAncestry.filter(
    (r) => r.isAouPopmax || r.matchedCount !== null || r.aouAf !== null || r.gnomadAf !== null,
  );
  const popmax = allAncestry.find((r) => r.isAouPopmax) ?? null;
  const largest = largestMatchedAncestry(allAncestry);
  const stacked = useMediaQuery(STACKED_QUERY);

  return (
    <div style={styles.root}>
      <header style={styles.identity}>
        <div style={styles.identityText}>
          {cohort ? (
            <div style={styles.nameLine}>
              <span style={styles.gene}>{cohort.gene}</span>
              {cohort.proteinChange && (
                <span style={styles.proteinChange} title={cohort.proteinChange}>
                  {cohort.proteinChange}
                </span>
              )}
            </div>
          ) : (
            <div style={styles.nameLine}>
              <span style={styles.gene}>Not observed in <AllOfUs /></span>
            </div>
          )}
          <div style={styles.descriptionLine}>
            {cohort && (
              <>
                <span>{cohort.consequence}</span>
                <span aria-hidden="true">·</span>
              </>
            )}
            <span style={styles.variantId}>{row.variant}</span>
            {!cohort && <span>· no annotations or frequencies to compare</span>}
          </div>
        </div>
        {cohort && (
          <dl style={styles.facts}>
            {cohort.clinvarSignificance && (
              <Fact label="ClinVar" title="ClinVar classification and review stars" first>
                <ClinvarBadge
                  significance={cohort.clinvarSignificance}
                  stars={cohort.clinvarStars}
                  conflicts={cohort.clinvarHasConflicts}
                  href={clinvarSearchUrl(cohort.variant)}
                />
              </Fact>
            )}
            <Fact label="SpliceAI" title="SpliceAI delta score, 0 to 1" first={!cohort.clinvarSignificance}>
              {cohort.spliceAi.toFixed(2)}
            </Fact>
            <Fact
              label="pLOF"
              title={
                cohort.plof
                  ? "LOFTEE loss-of-function call: HC is high confidence, LC low"
                  : "LOFTEE doesn't score this consequence type"
              }
            >
              {cohort.plof ?? "—"}
            </Fact>
          </dl>
        )}
      </header>

      <section style={styles.section} aria-labelledby="reviewVerdict">
        <SectionTitle
          id="reviewVerdict"
          tooltip={
            "Decided by the 95% confidence interval of the odds ratio, not by the point estimate. " +
            "Enriched: the whole interval is above 1. Depleted: the whole interval is below 1. " +
            `Similar: the interval rules out a ${SIMILARITY_FOLD}-fold difference either way. ` +
            "Inconclusive: the interval includes 1 and reaches past those bounds, so too few alleles were seen to say. " +
            `An enrichment call also needs at least ${MIN_ALLELES_FOR_ENRICHMENT} matched alleles; below that the interval isn't reliable.`
          }
        >
          Verdict
        </SectionTitle>
        <div
          role="status"
          style={{ ...styles.verdict, color: tone.ink, background: tone.fill }}
        >
          <div style={styles.verdictLine}>
            <VerdictGlyph tone={tone} />
            <span style={styles.verdictWord}>{tone.word}</span>
            {enrichment && enrichment.verdict !== "inconclusive" && (
              <span style={styles.verdictRatio}>{formatRatio(enrichment.ratio)}</span>
            )}
          </div>
          <p style={styles.verdictSentence}>{verdictSentence(row, describeAlternatives(phenotypes))}</p>
        </div>
      </section>

      {enrichment && matched && (
        <section style={styles.section} aria-labelledby="reviewEvidence">
          <SectionTitle
            id="reviewEvidence"
            tooltip="What stands behind the verdict. The test and the odds ratio compare matched participants with the rest of the cohort."
          >
            Evidence
          </SectionTitle>
          <div style={styles.evidence}>
            <StatTile
              label="Fisher's exact p"
              value={formatPValue(enrichment.pValue)}
              note={
                candidateCount > 1
                  ? `${formatPValue(Math.min(1, enrichment.pValue * candidateCount))} after Bonferroni, ${candidateCount} tests`
                  : "one test"
              }
              tooltip={
                "The chance of seeing a split of alternate alleles between matched participants and the rest of the cohort at least this uneven, if the phenotype filter made no difference. " +
                "Smaller is stronger evidence. Exact rather than approximate, so it holds up at the small counts typical here. " +
                "The figure underneath is the same p-value multiplied by the number of variants under review (Bonferroni), " +
                "the bar it must clear once you allow for having tested every candidate."
              }
            />
            <StatTile
              label="Odds ratio"
              value={enrichment.ci || enrichment.matchedAc > 0 ? formatSig(enrichment.oddsRatio) : "—"}
              note={enrichment.ci ? `95% CI ${formatInterval(enrichment.ci)}` : "no carriers on either side"}
              tooltip={
                "The odds of carrying this allele among matched participants divided by the odds among everyone else in the cohort: the standard case–control effect size, and the one that pairs with Fisher's test. " +
                "Above 1 means more common in the matched group. For a rare variant it is nearly the same as the fold change in the verdict; for a common one it runs higher. " +
                "The 95% interval underneath is exact, from the same model as Fisher's test, and it is what decides the verdict. With no carriers on one side, one end stays open: the data can only rule out a difference in the other direction."
              }
            />
            <StatTile
              label="Observed vs expected"
              value={
                <>
                  {formatInt(enrichment.matchedAc)}
                  <Connective>vs</Connective>
                  {formatExpected(enrichment.expectedMatchedAc)}
                </>
              }
              note={
                enrichment.expectedAdjustedAc !== null
                  ? `${formatExpected(enrichment.expectedAdjustedAc)} expected adjusting for ancestry`
                  : "expected at the cohort-wide rate"
              }
              tooltip={
                "Alternate alleles actually seen among matched participants, against how many the cohort-wide frequency predicts for a group this size. " +
                "The gap between the two is the signal in its most direct form. " +
                "The adjusted figure underneath re-weights that expectation by the matched cohort's ancestry makeup, using the variant's frequency in each All of Us ancestry group; " +
                "if it differs much from the cohort-wide expectation, ancestry rather than the phenotype filter may explain part of the gap."
              }
            />
            <StatTile
              label="Matched carriers"
              value={
                <>
                  {formatInt(matched.homozygotes + matched.heterozygotes)}
                  <Connective>of</Connective>
                  {formatInt(participantCount)}
                </>
              }
              note={`${formatInt(matched.homozygotes)} hom · ${formatInt(matched.heterozygotes)} het · ${formatInt(matched.clinvarPlpInTrans)} P/LP in trans`}
              tooltip={
                "How many of the matched participants carry at least one copy of this allele, split into homozygous and heterozygous carriers. " +
                "For a recessive condition, homozygotes and carriers with a ClinVar pathogenic or likely pathogenic variant in trans are the participants whose genotype could explain their phenotype."
              }
            />
          </div>
        </section>
      )}

      <div style={stacked ? undefined : styles.columns}>
        <section style={styles.section} aria-labelledby="reviewHeadToHead">
          <SectionTitle
            id="reviewHeadToHead"
            tooltip="The same measures for both sides, as in the table: all All of Us participants, and the phenotype-matched participants among them."
          >
            Head to head
          </SectionTitle>
          {cohort ? (
            <table style={styles.table}>
              <colgroup>
                <col style={{ width: "30%" }} />
                <col style={{ width: "35%" }} />
                <col style={{ width: "35%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={styles.th}>Measure</th>
                  <th style={styles.th}>All participants</th>
                  <th style={styles.th}>Phenotype-matched</th>
                </tr>
              </thead>
              <tbody>
                {/* TODO: replace AN / 2 with a real cohort participant count from the API. AN counts
                    called alleles, so halving it undercounts when calls are missing and is wrong for
                    sex-chromosome variants. The proper source is a count of participants with genomes
                    in the CDR (cb_search_person.has_whole_genome_variant), and the matched count
                    beside it should be restricted to participants with genomes too. */}
                <CompareRow
                  metric="Participants"
                  left={cohort.aouAllAn !== null ? formatInt(Math.round(cohort.aouAllAn / 2)) : null}
                  right={formatInt(participantCount)}
                />
                <CompareRow
                  metric="Allele frequency"
                  left={cohort.aouAllAf !== null ? <Frequency af={cohort.aouAllAf} /> : null}
                  right={matched ? <Frequency af={matched.cohortAf} /> : null}
                />
                <CompareRow
                  metric="AC / AN"
                  left={cohort.aouAllAc !== null && cohort.aouAllAn !== null ? formatAcAn(cohort.aouAllAc, cohort.aouAllAn) : null}
                  right={matched ? formatAcAn(matched.cohortAc, matched.cohortAn) : null}
                />
                <CompareRow
                  metric="Highest ancestry"
                  left={
                    popmax ? (
                      <span style={styles.populationLabel} title={`${SUBPOP_LABEL[popmax.population]}: the group where this variant is most frequent`}>
                        <span style={Style.colorDot(SUBPOP_COLOR[popmax.population])} />
                        {popmax.population}
                        {popmax.aouAf !== null && <span style={styles.value}>{formatAf(popmax.aouAf)}</span>}
                      </span>
                    ) : null
                  }
                  right={
                    largest ? (
                      <span style={styles.populationLabel} title={`${SUBPOP_LABEL[largest.population]}: the largest ancestry group among matched participants`}>
                        <span style={Style.colorDot(SUBPOP_COLOR[largest.population])} />
                        {largest.population}
                        {largest.matchedPercent !== null && (
                          <span style={styles.value}>{Math.round(largest.matchedPercent)}% of matched</span>
                        )}
                      </span>
                    ) : null
                  }
                />
              </tbody>
            </table>
          ) : (
            <div style={styles.empty}>Nothing to compare: the variant has no cohort-wide data.</div>
          )}
        </section>

        <section style={styles.section} aria-labelledby="reviewAncestry">
          <SectionTitle
            id="reviewAncestry"
            tooltip="Each All of Us ancestry group: how much of the phenotype-matched cohort it makes up, beside the variant's cohort-wide frequency within that group. gnomAD's figure is shown where it has the same group. The shaded row is where the variant is most frequent."
          >
            Ancestry context
          </SectionTitle>
          {cohort ? (
            <table style={styles.table}>
              <colgroup>
                <col style={{ width: "15%" }} />
                <col style={{ width: "31%" }} />
                <col style={{ width: "16%" }} />
                <col style={{ width: "22%" }} />
                <col style={{ width: "16%" }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={styles.th}>Ancestry</th>
                  <th style={styles.th}>Share of matched</th>
                  <th style={styles.th}>
                    <AllOfUs /> AF
                  </th>
                  <th style={styles.th}>
                    <AllOfUs /> AC / AN
                  </th>
                  <th style={styles.th}>gnomAD AF</th>
                </tr>
              </thead>
              <tbody>
                {ancestry.map((r) => (
                  <tr key={r.population} style={r.isAouPopmax ? { background: POPMAX_BACKGROUND } : undefined}>
                    <td style={styles.td}>
                      <span style={styles.populationLabel} title={SUBPOP_LABEL[r.population]}>
                        <span style={Style.colorDot(SUBPOP_COLOR[r.population])} />
                        {r.population}
                      </span>
                    </td>
                    <td style={styles.td}>
                      {r.matchedPercent !== null && r.matchedCount !== null ? (
                        <span style={styles.value}>
                          <span style={{ ...styles.shareBar, width: Math.max(2, r.matchedPercent * 0.6) }} aria-hidden="true" />
                          {Math.round(r.matchedPercent)}% ({formatInt(r.matchedCount)})
                        </span>
                      ) : (
                        <NotAvailable />
                      )}
                    </td>
                    <td style={styles.td} title={r.aouAf !== null ? exactAf(r.aouAf) : undefined}>
                      {r.aouAf !== null ? <span style={styles.value}>{formatAf(r.aouAf)}</span> : <NotAvailable />}
                    </td>
                    <td style={styles.td}>
                      {r.aouAc !== null && r.aouAn !== null ? (
                        <span style={styles.value}>{formatAcAn(r.aouAc, r.aouAn)}</span>
                      ) : (
                        <NotAvailable />
                      )}
                    </td>
                    <td style={styles.td} title={r.gnomadAf !== null ? exactAf(r.gnomadAf) : undefined}>
                      {r.gnomadAf !== null ? <span style={styles.value}>{formatAf(r.gnomadAf)}</span> : <NotAvailable />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={styles.empty}>No population frequencies for this variant.</div>
          )}
        </section>
      </div>
    </div>
  );
}

/**
 * One or two lines under the verdict: what the numbers mean for this phenotype filter, with the
 * counts they rest on. `condition` is the filter's conditions as alternatives, "A or B".
 */
function verdictSentence(row: ComparisonRow, condition: string): ReactNode {
  const { cohort, matched, enrichment } = row;
  if (!cohort) return "This variant has no cohort-wide frequency, so there is nothing to compare against.";
  if (!matched) return "No phenotype-matched statistics exist for this variant yet.";
  if (!enrichment) {
    const exceeds =
      cohort.aouAllAc !== null && cohort.aouAllAn !== null && (matched.cohortAc > cohort.aouAllAc || matched.cohortAn > cohort.aouAllAn);
    return exceeds
      ? "The matched participants' counts exceed the cohort-wide counts, so the two sources disagree and no comparison is possible."
      : "Cohort-wide allele counts are missing for this variant.";
  }
  const counts = `${formatInt(enrichment.matchedAc)} allele${enrichment.matchedAc === 1 ? "" : "s"} observed among participants with ${condition}, ${formatExpected(enrichment.expectedMatchedAc)} expected at the cohort-wide rate`;
  switch (enrichment.verdict) {
    case "enriched":
      return <>{counts}: more than chance can explain.</>;
    case "depleted":
      return <>{counts}: fewer than chance allows.</>;
    case "similar":
      return (
        <>
          {counts}. The cohort is large enough to rule out a {SIMILARITY_FOLD}-fold difference either way.
        </>
      );
    default:
      return (
        <>
          {counts}. Too few alleles to say
          {enrichment.lean ? `; what there is leans toward ${enrichment.lean} than expected` : ""}
          {enrichment.ci && enrichment.ci[0] > 1 && enrichment.matchedAc < MIN_ALLELES_FOR_ENRICHMENT
            ? `. The interval sits above 1, but ${MIN_ALLELES_FOR_ENRICHMENT} alleles are the minimum for a call.`
            : "."}
        </>
      );
  }
}

interface StatTileProps {
  label: string;
  /** The headline figure; join two figures with <Connective>. */
  value: ReactNode;
  note: string;
  /** What the figure is and how to read it, for the info icon beside the label. */
  tooltip: string;
}

function StatTile({ label, value, note, tooltip }: StatTileProps) {
  return (
    <div style={styles.tile}>
      <span style={Style.elements.eyebrow}>
        <InfoLabel tooltip={tooltip}>{label}</InfoLabel>
      </span>
      <span style={styles.tileValue}>{value}</span>
      <span style={styles.tileNote}>{note}</span>
    </div>
  );
}

/** A word joining two figures in a stat tile, with the spaces around it. */
function Connective({ children }: { children: string }) {
  return <span style={styles.tileConnective}> {children} </span>;
}

/** One labelled annotation in the header: a small label over its value. */
function Fact({ label, title, first = false, children }: { label: string; title: string; first?: boolean; children: ReactNode }) {
  return (
    <div style={{ ...styles.fact, ...(first ? styles.factFirst : undefined) }} title={title}>
      <dt style={Style.elements.eyebrow}>{label}</dt>
      <dd style={{ ...styles.factValue, margin: 0 }}>{children}</dd>
    </div>
  );
}

function SectionTitle({ id, children, tooltip }: { id: string; children: ReactNode; tooltip?: string }) {
  return (
    <h3 id={id} style={styles.sectionTitle}>
      {children}
      {tooltip && <InfoTooltip text={tooltip} style={{ marginTop: -4, marginBottom: -4 }} />}
    </h3>
  );
}

interface CompareRowProps {
  metric: string;
  /** Rendered as-is; null draws the "not available" dash. */
  left: ReactNode | null;
  right: ReactNode | null;
}

function CompareRow({ metric, left, right }: CompareRowProps) {
  return (
    <tr>
      <td style={{ ...styles.td, ...styles.metric }}>{metric}</td>
      <td style={styles.td}>{left === null ? <NotAvailable /> : <span style={styles.value}>{left}</span>}</td>
      <td style={styles.td}>{right === null ? <NotAvailable /> : <span style={styles.value}>{right}</span>}</td>
    </tr>
  );
}

/** The headline figure of the table, with the exact value on hover when the display rounds it. */
function Frequency({ af }: { af: number }) {
  return (
    <span style={{ ...styles.value, ...styles.valueStrong }} title={exactAf(af) ? `Exactly ${exactAf(af)}` : undefined}>
      {formatAf(af)}
    </span>
  );
}
