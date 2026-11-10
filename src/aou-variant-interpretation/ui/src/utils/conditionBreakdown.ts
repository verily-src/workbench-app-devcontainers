import type { ConditionOverlapCell, MatchedConcept } from "../api/conditions";
import colors, { CONDITION_SERIES } from "../libs/colors";
import type { BreakdownSegment } from "../types/results";

/**
 * The Condition breakdown: one segment per condition for the participants recorded with only
 * that one, then one for everyone recorded with more than one of them. Folded from the search's
 * overlap cells, so the segments are disjoint and sum to the matched count, like the other
 * breakdowns' do. A condition nobody has on its own, or no overlap at all, has no segment.
 */
export function conditionBreakdown(
  concepts: MatchedConcept[],
  cells: ConditionOverlapCell[],
  participantCount: number,
): BreakdownSegment[] {
  if (participantCount <= 0) return [];
  const percent = (count: number) => (count / participantCount) * 100;
  const segments: BreakdownSegment[] = [];
  concepts.forEach((concept, index) => {
    const own = cells.find((cell) => cell.conceptIds.length === 1 && cell.conceptIds[0] === concept.conceptId);
    if (own && own.count > 0) {
      segments.push({
        label: `${concept.name} only`,
        count: own.count,
        percent: percent(own.count),
        color: CONDITION_SERIES[index % CONDITION_SERIES.length],
      });
    }
  });
  const shared = cells.filter((cell) => cell.conceptIds.length > 1).reduce((sum, cell) => sum + cell.count, 0);
  if (shared > 0) {
    segments.push({ label: "More than one", count: shared, percent: percent(shared), color: colors.conditionOverlap });
  }
  return segments;
}
