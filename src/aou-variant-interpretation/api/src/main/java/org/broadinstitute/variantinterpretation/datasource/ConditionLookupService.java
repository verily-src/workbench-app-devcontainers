package org.broadinstitute.variantinterpretation.datasource;

import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.QueryParameterValue;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.broadinstitute.variantinterpretation.util.BigQueryValues.intValue;

import org.broadinstitute.variantinterpretation.model.ConditionCandidates;
import org.broadinstitute.variantinterpretation.model.ConditionConcept;
import org.broadinstitute.variantinterpretation.model.ConditionOverlapCell;
import org.broadinstitute.variantinterpretation.model.ConditionSearch;
import org.broadinstitute.variantinterpretation.model.MatchedConcept;
import org.broadinstitute.variantinterpretation.ontology.HpoLookupService;
import org.springframework.stereotype.Service;

/**
 * Free text -> condition concepts (the type-ahead), and picked concepts -> participant count,
 * against the All of Us {@code cb_criteria}, {@code concept_ancestor} and
 * {@code condition_occurrence} tables.
 *
 * <p>Three things here are worth noting:
 *
 * <ul>
 *   <li><b>Descendant expansion through {@code concept_ancestor}.</b> EHR data lands on
 *       specific leaf concepts, not the parent that was searched for, so matching the seed
 *       concept alone will undercount matches. Against the synthetic fixture, seeding on
 *       Tetralogy of Fallot returns 49 participants expanded and 40 unexpanded.
 *   <li><b>Ranking by {@code est_count}.</b> The only reason to use {@code cb_criteria}
 *       instead of the plain vocabulary tables. A concept can be perfectly named, perfectly
 *       standard, and have zero participants in this CDR — which is invisible in
 *       {@code concept}. Ranking by count puts the concepts someone is likely to mean at the
 *       top of the type-ahead.
 *   <li><b>Several concepts are OR'd.</b> A participant matches a search if any of the picked
 *       concepts, or a descendant of any of them, is recorded for them: the same rule one concept
 *       already uses over its descendants, and the Cohort Builder's rule within a criteria group.
 *       One query counts participants by the exact set of picked concepts they have; the union,
 *       each concept's own count and the overlap between them all fall out of those cells.
 * </ul>
 */
@Service
public class ConditionLookupService {

  // Fixed CDR table names; only the dataset varies. See BigQueryProperties#cdrTable(String).
  private static final String CB_CRITERIA = "cb_criteria";
  private static final String CONCEPT_ANCESTOR = "concept_ancestor";
  private static final String CONDITION_OCCURRENCE = "condition_occurrence";

  /** Every CDR table this service queries, for the access check in SystemController. */
  public static final List<String> CDR_TABLES =
      List.of(CB_CRITERIA, CONCEPT_ANCESTOR, CONDITION_OCCURRENCE);

  // Only show the top 50 candidates in the type-ahead
  private static final int CANDIDATES_LIMIT = 50;

  /**
   * Stop words to exclude from token matching.
   * For example, we don't want searching for "Fallot tetralogy" to
   * not match "Tetralogy of Fallot" just because "of" is a stop word.
   */
  private static final Set<String> STOP_WORDS =
      Set.of("of", "the", "and", "or", "with", "in", "to", "for", "by", "on", "at", "as");

  /**
   * Substring matching, not whole-token matching. BigQuery's {@code SEARCH()} works on this
   * table and would avoid spurious substring hits, but it matches whole tokens only, so
   * "diabet" finds nothing — a bad trade for a search box someone types into. If the enclave
   * turns out to need token semantics, this predicate is the only thing that changes.
   *
   * <p>{@code est_count} is SAFE_CAST rather than read as an INT64 because the column has been
   * seen typed STRING in some CDR releases, and carries -1 as well as NULL.
   */
  private static final String SEARCH_CONCEPTS_SQL =
      """
      SELECT DISTINCT
          concept_id,
          name,
          SAFE_CAST(est_count AS INT64) AS est_count
      FROM %s
      WHERE is_standard = 1
        AND concept_id IS NOT NULL
        AND domain_id = "CONDITION"
        AND %s
      ORDER BY LOWER(TRIM(name)) = @exactName DESC, est_count DESC NULLS LAST
      LIMIT %d
      """;

  /**
   * Resolves the concepts the user actually picked. Filtered to standard condition concepts on
   * purpose: an id that isn't one is dropped rather than seeded on, so a stale or hand-edited
   * URL can't produce a cohort counted over something that isn't a condition.
   */
  private static final String RESOLVE_CONCEPTS_SQL =
      """
      SELECT DISTINCT
          concept_id,
          name,
          SAFE_CAST(est_count AS INT64) AS est_count
      FROM %s
      WHERE is_standard = 1
        AND domain_id = "CONDITION"
        AND concept_id IN UNNEST(@conceptIds)
      """;

  /**
   * Matched participants grouped by the exact set of picked concepts they have, each concept
   * taken over its descendants. One row per non-empty combination, at most 2^n - 1 of them: the
   * cells are disjoint, their sum is the union (the OR), and a concept's own count is the sum of
   * the cells that contain it. Grouping by person first and the set second keeps person ids
   * inside BigQuery. The set is keyed as a string because BigQuery can't group by an array.
   */
  private static final String OVERLAP_CELLS_SQL =
      """
      WITH per_person AS (
          SELECT co.person_id,
                 ARRAY_AGG(DISTINCT ca.ancestor_concept_id ORDER BY ca.ancestor_concept_id) AS concept_ids
          FROM %s co
          JOIN %s ca ON ca.descendant_concept_id = co.condition_concept_id
          WHERE ca.ancestor_concept_id IN UNNEST(@conceptIds)
          GROUP BY co.person_id
      )
      SELECT ARRAY_TO_STRING(ARRAY(SELECT CAST(c AS STRING) FROM UNNEST(concept_ids) c), ',') AS cell,
             COUNT(*) AS participants
      FROM per_person
      GROUP BY cell
      """;

  private final BigQueryService bigQuery;
  private final BigQueryProperties properties;
  private final HpoLookupService hpo;

  public ConditionLookupService(BigQueryService bigQuery, BigQueryProperties properties, HpoLookupService hpo) {
    this.bigQuery = bigQuery;
    this.properties = properties;
    this.hpo = hpo;
  }

  /**
   * Text to ranked candidates, with no expansion and no participant count.
   * This is what the phenotype search box's dropdown runs on every keystroke, so it stays one
   * query against {@code cb_criteria}.
   *
   * <p>A blank term yields no candidates rather than an error or a match-everything query, so
   * a type-ahead doesn't have to special-case the empty box.
   */
  public ConditionCandidates candidates(String term) {
    String trimmed = term == null ? "" : term.trim();
    return new ConditionCandidates().term(trimmed).candidates(findRankedCandidates(trimmed));
  }

  /**
   * The participant count for the concepts the user picked from the type-ahead: how many have
   * any of them, plus each concept's own count.
   *
   * <p>Returns null when nothing was picked, so the response field stays null, the same as
   * leaving the phenotype field empty. There's deliberately no free-text fallback: searching
   * typed text and choosing a match on the user's behalf can count a different concept than the
   * one they meant. Duplicates are dropped, keeping first-seen order; an id that isn't a
   * standard condition concept is dropped too, and when none are left the count is null.
   */
  public ConditionSearch search(List<Long> conceptIds) {
    List<Long> requested = conceptIds == null ? List.of() : conceptIds.stream().filter(id -> id != null).distinct().toList();
    if (requested.isEmpty()) {
      return null;
    }
    List<ConditionConcept> resolved = resolveConcepts(requested);
    if (resolved.isEmpty()) {
      return new ConditionSearch().conceptIds(requested).concepts(List.of()).participantCount(null);
    }
    List<Long> resolvedIds = resolved.stream().map(ConditionConcept::getConceptId).toList();
    List<ConditionOverlapCell> cells = overlapCells(resolvedIds);
    List<MatchedConcept> matched =
        resolved.stream()
            .map(
                concept ->
                    new MatchedConcept()
                        .conceptId(concept.getConceptId())
                        .name(concept.getName())
                        .estimatedParticipantCount(concept.getEstimatedParticipantCount().orElse(null))
                        .hpo(concept.getHpo().orElse(null))
                        .participantCount(
                            cells.stream()
                                .filter(cell -> cell.getConceptIds().contains(concept.getConceptId()))
                                .mapToInt(ConditionOverlapCell::getCount)
                                .sum()))
            .toList();
    int union = cells.stream().mapToInt(ConditionOverlapCell::getCount).sum();
    return new ConditionSearch()
        .conceptIds(requested)
        .concepts(matched)
        .participantCount(union)
        .conditionOverlap(cells);
  }

  /** The standard condition concepts among the ids, in the ids' order; the rest are left out. */
  private List<ConditionConcept> resolveConcepts(List<Long> conceptIds) {
    var query =
        QueryJobConfiguration.newBuilder(
                RESOLVE_CONCEPTS_SQL.formatted(properties.cdrTableRef(CB_CRITERIA)))
            .addNamedParameter("conceptIds", conceptIdsParameter(conceptIds));
    Map<Long, ConditionConcept> byId = new HashMap<>();
    for (ConditionConcept concept : toConcepts(bigQuery.query(query, "Resolve concepts"))) {
      byId.putIfAbsent(concept.getConceptId(), concept);
    }
    return conceptIds.stream().map(byId::get).filter(concept -> concept != null).toList();
  }

  /**
   * Sorted, whatever order they were picked in: BigQuery's result cache keys on the exact query
   * and parameters, so the same set in another order would otherwise be a cache miss and a
   * second scan. Nothing here depends on the order -- resolved concepts are put back in request
   * order by {@link #resolveConcepts}, and the counts are keyed by id.
   */
  private static QueryParameterValue conceptIdsParameter(List<Long> conceptIds) {
    return QueryParameterValue.array(conceptIds.stream().sorted().toArray(Long[]::new), Long.class);
  }

  /** Empty for a blank term, or one with no usable tokens. */
  private List<ConditionConcept> findRankedCandidates(String trimmedTerm) {
    if (trimmedTerm.isEmpty()) {
      return List.of();
    }
    List<String> terms = matchTerms(trimmedTerm);
    return terms.isEmpty() ? List.of() : findCandidates(trimmedTerm, terms);
  }

  /**
   * Tokenizes the query the way the matching needs it: lowercased, punctuation stripped,
   * single characters and stop words dropped.
   *
   * <p>Falls back to the unfiltered tokens when every one of them is a stop word, so that
   * searching "in the" is a search for something rather than a match against everything.
   */
  static List<String> matchTerms(String text) {
    List<String> tokens =
        Stream.of(text.toLowerCase(Locale.ROOT).split("\\s+"))
            .map(t -> t.replaceAll("^[,.;:()]+|[,.;:()]+$", ""))
            .filter(t -> t.length() > 1)
            .toList();
    List<String> kept = tokens.stream().filter(t -> !STOP_WORDS.contains(t)).toList();
    return kept.isEmpty() ? tokens : kept;
  }

  /**
   * Escapes a term for use inside a LIKE pattern. The term is already a bound parameter, so
   * this isn't about injection: it's that "%" and "_" in what someone typed are LIKE
   * wildcards, and a search for "type_2" should not also match "type 2".
   */
  static String likePattern(String term) {
    String escaped =
        term.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_");
    return "%" + escaped + "%";
  }

  private List<ConditionConcept> findCandidates(String rawTerm, List<String> terms) {
    // One bound parameter per term, ANDed: every term must appear somewhere in full_text,
    // which is the concept name and its synonyms concatenated.
    List<String> predicates = new ArrayList<>();
    for (int i = 0; i < terms.size(); i++) {
      predicates.add("LOWER(full_text) LIKE @term" + i);
    }

    var builder =
        QueryJobConfiguration.newBuilder(
                SEARCH_CONCEPTS_SQL.formatted(
                    properties.cdrTableRef(CB_CRITERIA),
                    String.join(" AND ", predicates),
                    CANDIDATES_LIMIT))
            .addNamedParameter("exactName", QueryParameterValue.string(rawTerm.toLowerCase(Locale.ROOT)));
    for (int i = 0; i < terms.size(); i++) {
      builder.addNamedParameter("term" + i, QueryParameterValue.string(likePattern(terms.get(i))));
    }

    return toConcepts(bigQuery.query(builder, "Condition candidates"));
  }

  /** Each row as a concept, paired with its HPO term by name (see HpoLookupService). */
  private List<ConditionConcept> toConcepts(Iterable<FieldValueList> rows) {
    List<ConditionConcept> concepts = new ArrayList<>();
    for (FieldValueList row : rows) {
      String name = row.get("name").getStringValue();
      concepts.add(
          new ConditionConcept()
              .conceptId(row.get("concept_id").getLongValue())
              .name(name)
              .estimatedParticipantCount(intValue(row, "est_count"))
              .hpo(hpo.match(name).orElse(null)));
    }
    return concepts;
  }

  /**
   * The matched participants by the exact set of concepts they have, in a stable order: cells
   * with fewer concepts first, then by the concepts' request order. Each cell's ids are in
   * request order too, so the UI can name it without sorting.
   */
  private List<ConditionOverlapCell> overlapCells(List<Long> conceptIds) {
    var query =
        QueryJobConfiguration.newBuilder(
                OVERLAP_CELLS_SQL.formatted(
                    properties.cdrTableRef(CONDITION_OCCURRENCE),
                    properties.cdrTableRef(CONCEPT_ANCESTOR)))
            .addNamedParameter("conceptIds", conceptIdsParameter(conceptIds));
    List<ConditionOverlapCell> cells = new ArrayList<>();
    for (FieldValueList row : bigQuery.query(query, "Cohort overlap")) {
      Set<Long> inCell =
          Stream.of(row.get("cell").getStringValue().split(",")).map(Long::valueOf).collect(Collectors.toSet());
      cells.add(
          new ConditionOverlapCell()
              .conceptIds(conceptIds.stream().filter(inCell::contains).toList())
              .count((int) row.get("participants").getLongValue()));
    }
    Comparator<ConditionOverlapCell> bySize = Comparator.comparingInt(cell -> cell.getConceptIds().size());
    cells.sort(bySize.thenComparingInt(cell -> conceptIds.indexOf(cell.getConceptIds().get(0))));
    return cells;
  }
}
