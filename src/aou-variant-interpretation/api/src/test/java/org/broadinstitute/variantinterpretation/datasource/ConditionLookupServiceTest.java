package org.broadinstitute.variantinterpretation.datasource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.tuple;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.cloud.bigquery.Field;
import com.google.cloud.bigquery.FieldValue;
import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.QueryParameterValue;
import com.google.cloud.bigquery.StandardSQLTypeName;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.broadinstitute.variantinterpretation.model.ConditionOverlapCell;
import org.broadinstitute.variantinterpretation.model.ConditionSearch;
import org.broadinstitute.variantinterpretation.model.HpoTerm;
import org.broadinstitute.variantinterpretation.model.MatchedConcept;
import org.broadinstitute.variantinterpretation.ontology.HpoLookupService;
import org.broadinstitute.variantinterpretation.ontology.HpoLookupServiceTest;
import org.junit.jupiter.api.Test;

/**
 * Covers the pieces of the lookup that don't need BigQuery: how free text becomes match terms,
 * how those terms become LIKE patterns, and how a search over several concepts puts its three
 * queries together (against a scripted BigQuery). The SQL itself is exercised against the
 * synthetic fixture in the dev dataset -- see data/README.md.
 */
class ConditionLookupServiceTest {

  private static final long TETRALOGY = 9000010L;
  private static final long HCM = 9000040L;

  /** The trimmed ontology in test resources; see HpoLookupServiceTest for what it pairs. */
  private static final HpoLookupService HPO = HpoLookupServiceTest.trimmed();

  private static final Field[] CONCEPT_ROW = {
    Field.of("concept_id", StandardSQLTypeName.INT64),
    Field.of("name", StandardSQLTypeName.STRING),
    Field.of("est_count", StandardSQLTypeName.INT64),
  };
  private static final Field[] CELL_ROW = {
    Field.of("cell", StandardSQLTypeName.STRING),
    Field.of("participants", StandardSQLTypeName.INT64),
  };

  private static FieldValueList row(Field[] schema, Object... values) {
    List<FieldValue> cells = new ArrayList<>();
    for (Object value : values) {
      cells.add(FieldValue.of(FieldValue.Attribute.PRIMITIVE, value == null ? null : String.valueOf(value)));
    }
    return FieldValueList.of(cells, schema);
  }

  /**
   * A BigQuery that answers the service's two condition queries from fixed rows, told apart by
   * their SQL, and keeps the concept ids each was asked about.
   */
  private static final class ScriptedBigQuery {
    final List<FieldValueList> concepts = new ArrayList<>();
    final List<FieldValueList> cells = new ArrayList<>();
    final List<String> queriesRun = new ArrayList<>();
    final List<List<Long>> idsAsked = new ArrayList<>();

    ConditionLookupService service() {
      BigQueryService bigQuery = mock(BigQueryService.class);
      when(bigQuery.query(any(), any()))
          .thenAnswer(
              invocation -> {
                QueryJobConfiguration config = invocation.<QueryJobConfiguration.Builder>getArgument(0).build();
                String sql = config.getQuery();
                QueryParameterValue ids = config.getNamedParameters().get("conceptIds");
                idsAsked.add(ids.getArrayValues().stream().map(v -> Long.valueOf(v.getValue())).toList());
                if (sql.contains("GROUP BY cell")) {
                  queriesRun.add("cells");
                  return cells;
                }
                queriesRun.add("resolve");
                return concepts;
              });
      return new ConditionLookupService(
          bigQuery, new BigQueryProperties("billing", "project", "dataset", "vat", "cdr-project.cdr"), HPO);
    }
  }

  @Test
  void matchTerms_lowercasesAndStripsPunctuation() {
    assertThat(ConditionLookupService.matchTerms("Tetralogy of Fallot,"))
        .containsExactly("tetralogy", "fallot");
  }

  /**
   * The stopword regression. Requiring the literal token "of" would exclude the inverted
   * synonym "Fallot tetralogy" -- exactly the word-order case this matching exists to catch.
   * If someone deletes STOP_WORDS as cosmetic, this is what should fail.
   */
  @Test
  void matchTerms_dropsConnectives() {
    assertThat(ConditionLookupService.matchTerms("tetralogy of fallot")).doesNotContain("of");
    assertThat(ConditionLookupService.matchTerms("diabetes with renal complications"))
        .containsExactly("diabetes", "renal", "complications");
  }

  /** Single characters carry no signal and match nearly everything as a substring. */
  @Test
  void matchTerms_dropsSingleCharacterTokens() {
    assertThat(ConditionLookupService.matchTerms("type 2 diabetes"))
        .containsExactly("type", "diabetes");
  }

  /**
   * A query of nothing but connectives falls back to the unfiltered tokens, so it searches
   * for something rather than reducing to an empty predicate that matches every row.
   */
  @Test
  void matchTerms_fallsBackWhenEveryTokenIsAStopWord() {
    assertThat(ConditionLookupService.matchTerms("of the")).containsExactly("of", "the");
  }

  @Test
  void matchTerms_isEmptyForTextWithNoUsableTokens() {
    assertThat(ConditionLookupService.matchTerms("a ( )")).isEmpty();
  }

  @Test
  void likePattern_wrapsInWildcards() {
    assertThat(ConditionLookupService.likePattern("fallot")).isEqualTo("%fallot%");
  }

  /**
   * "%" and "_" typed by a user are LIKE wildcards. Escaping them is not about injection --
   * the term is a bound parameter either way -- but about "type_2" not also matching
   * "type 2". Verified against BigQuery: an escaped underscore matches literally.
   */
  @Test
  void likePattern_escapesWildcardsInUserInput() {
    assertThat(ConditionLookupService.likePattern("type_2")).isEqualTo("%type\\_2%");
    assertThat(ConditionLookupService.likePattern("50%")).isEqualTo("%50\\%%");
    assertThat(ConditionLookupService.likePattern("a\\b")).isEqualTo("%a\\\\b%");
  }

  @Test
  void likePattern_leavesOrdinaryPunctuationAlone() {
    assertThat(ConditionLookupService.likePattern("fallot's")).isEqualTo("%fallot's%");
  }

  /** Nothing picked means no query, and leaves the response field null. */
  @Test
  void search_returnsNullWhenNoConceptWasPicked() {
    // A null BigQuery client is the assertion: touching it would NPE.
    ConditionLookupService service = new ConditionLookupService(null, null, HPO);
    assertThat(service.search(null)).isNull();
    assertThat(service.search(List.of())).isNull();
    assertThat(service.search(Arrays.asList((Long) null))).isNull();
  }

  /**
   * Two concepts: the cells say who has which. The union is their sum, each concept's own count
   * is the sum of the cells containing it, and the cells come back with fewer concepts first.
   */
  @Test
  void search_countsParticipantsWithAnyOfTheConcepts() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    // Resolved in the other order, to show the response keeps the request's.
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", 47));
    bigQuery.concepts.add(row(CONCEPT_ROW, HCM, "Hypertrophic cardiomyopathy", 212));
    // BigQuery keys each cell by its sorted ids; three participants have both.
    bigQuery.cells.add(row(CELL_ROW, TETRALOGY + "," + HCM, 3));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 46));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(HCM), 211));

    ConditionSearch search = bigQuery.service().search(List.of(HCM, TETRALOGY));

    assertThat(search.getConceptIds()).containsExactly(HCM, TETRALOGY);
    assertThat(search.getConcepts())
        .extracting(
            MatchedConcept::getConceptId,
            MatchedConcept::getName,
            m -> m.getEstimatedParticipantCount().orElse(null),
            MatchedConcept::getParticipantCount)
        .containsExactly(
            tuple(HCM, "Hypertrophic cardiomyopathy", 212, 214), tuple(TETRALOGY, "Tetralogy of Fallot", 47, 49));
    assertThat(search.getParticipantCount().orElse(null)).isEqualTo(260);
    // Each resolved concept carries the HPO term its name pairs with.
    assertThat(search.getConcepts())
        .extracting(m -> m.getHpo().map(HpoTerm::getId).orElse(null))
        .containsExactly("HP:0001639", "HP:0001636");
    // Singles in request order, then the pair, whose ids are in request order too.
    assertThat(search.getConditionOverlap())
        .extracting(ConditionOverlapCell::getConceptIds, ConditionOverlapCell::getCount)
        .containsExactly(tuple(List.of(HCM), 211), tuple(List.of(TETRALOGY), 46), tuple(List.of(HCM, TETRALOGY), 3));
    assertThat(bigQuery.queriesRun).containsExactly("resolve", "cells");
  }

  /**
   * The ids go to BigQuery sorted, whatever order they were picked in, so the same set in another
   * order is the same query text and parameters and hits BigQuery's result cache instead of
   * scanning again. The response still keeps the request's order.
   */
  @Test
  void search_sendsTheIdsSortedSoBigQueryCanCacheTheQuery() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", 47));
    bigQuery.concepts.add(row(CONCEPT_ROW, HCM, "Hypertrophic cardiomyopathy", 212));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 49));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(HCM), 214));

    ConditionSearch search = bigQuery.service().search(List.of(HCM, TETRALOGY));

    assertThat(bigQuery.idsAsked).hasSize(2).allSatisfy(ids -> assertThat(ids).containsExactly(TETRALOGY, HCM));
    assertThat(search.getConceptIds()).containsExactly(HCM, TETRALOGY);
    assertThat(search.getConcepts()).extracting(MatchedConcept::getConceptId).containsExactly(HCM, TETRALOGY);
  }

  /** One concept: one cell, which is its own count and the union. */
  @Test
  void search_hasOneCellForOneConcept() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", 47));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 49));

    ConditionSearch search = bigQuery.service().search(List.of(TETRALOGY));

    assertThat(search.getParticipantCount().orElse(null)).isEqualTo(49);
    assertThat(search.getConcepts().get(0).getParticipantCount()).isEqualTo(49);
    assertThat(search.getConditionOverlap()).extracting(ConditionOverlapCell::getCount).containsExactly(49);
    assertThat(bigQuery.queriesRun).containsExactly("resolve", "cells");
  }

  /**
   * An id that isn't a standard condition concept is dropped from the cohort but still echoed in
   * conceptIds, so the UI can say what was asked for. The rest still count.
   */
  @Test
  void search_dropsAnIdThatIsntAConditionAndCountsTheRest() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", null));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 49));

    ConditionSearch search = bigQuery.service().search(List.of(123L, TETRALOGY));

    assertThat(search.getConceptIds()).containsExactly(123L, TETRALOGY);
    assertThat(search.getConcepts()).extracting(MatchedConcept::getConceptId).containsExactly(TETRALOGY);
    assertThat(search.getConcepts().get(0).getEstimatedParticipantCount().orElse(null)).isNull();
    assertThat(search.getParticipantCount().orElse(null)).isEqualTo(49);
    // The cells are asked about the resolved concept only.
    assertThat(bigQuery.idsAsked.get(1)).containsExactly(TETRALOGY);
  }

  /** Nothing resolved: no cohort to count, and the response says so with a null count. */
  @Test
  void search_hasANullCountWhenNoIdResolves() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();

    ConditionSearch search = bigQuery.service().search(List.of(123L));

    assertThat(search.getConceptIds()).containsExactly(123L);
    assertThat(search.getConcepts()).isEmpty();
    assertThat(search.getConditionOverlap()).isEmpty();
    assertThat(search.getParticipantCount().isPresent()).isTrue();
    assertThat(search.getParticipantCount().orElse(null)).isNull();
    assertThat(bigQuery.queriesRun).containsExactly("resolve");
  }

  /** The same id twice is one concept, asked about once. */
  @Test
  void search_collapsesDuplicateIds() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", 47));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 49));

    ConditionSearch search = bigQuery.service().search(List.of(TETRALOGY, TETRALOGY));

    assertThat(search.getConceptIds()).containsExactly(TETRALOGY);
    assertThat(search.getConcepts()).hasSize(1);
    assertThat(bigQuery.idsAsked.get(0)).containsExactly(TETRALOGY);
  }

  /** A resolved concept nobody is recorded with is in no cell, and reads as 0. */
  @Test
  void search_readsAConceptInNoCellAsZero() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", 47));
    bigQuery.concepts.add(row(CONCEPT_ROW, HCM, "Hypertrophic cardiomyopathy", 0));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 49));

    ConditionSearch search = bigQuery.service().search(List.of(TETRALOGY, HCM));

    assertThat(search.getConcepts())
        .extracting(MatchedConcept::getConceptId, MatchedConcept::getParticipantCount)
        .containsExactly(tuple(TETRALOGY, 49), tuple(HCM, 0));
    assertThat(search.getParticipantCount().orElse(null)).isEqualTo(49);
  }

  /** Three concepts: cells of every size, ordered by size then by the first concept's request position. */
  @Test
  void search_ordersCellsBySizeThenRequestOrder() {
    ScriptedBigQuery bigQuery = new ScriptedBigQuery();
    long lqt = 9000060L;
    bigQuery.concepts.add(row(CONCEPT_ROW, HCM, "Hypertrophic cardiomyopathy", 212));
    bigQuery.concepts.add(row(CONCEPT_ROW, lqt, "Long QT syndrome", 128));
    bigQuery.concepts.add(row(CONCEPT_ROW, TETRALOGY, "Tetralogy of Fallot", 47));
    bigQuery.cells.add(row(CELL_ROW, TETRALOGY + "," + HCM + "," + lqt, 1));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(lqt), 119));
    bigQuery.cells.add(row(CELL_ROW, HCM + "," + lqt, 11));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(HCM), 201));
    bigQuery.cells.add(row(CELL_ROW, TETRALOGY + "," + HCM, 1));
    bigQuery.cells.add(row(CELL_ROW, String.valueOf(TETRALOGY), 47));

    ConditionSearch search = bigQuery.service().search(List.of(HCM, lqt, TETRALOGY));

    assertThat(search.getConditionOverlap())
        .extracting(ConditionOverlapCell::getConceptIds, ConditionOverlapCell::getCount)
        .containsExactly(
            tuple(List.of(HCM), 201),
            tuple(List.of(lqt), 119),
            tuple(List.of(TETRALOGY), 47),
            tuple(List.of(HCM, lqt), 11),
            tuple(List.of(HCM, TETRALOGY), 1),
            tuple(List.of(HCM, lqt, TETRALOGY), 1));
    assertThat(search.getParticipantCount().orElse(null)).isEqualTo(380);
    assertThat(search.getConcepts()).extracting(MatchedConcept::getParticipantCount).containsExactly(214, 131, 49);
  }

  /**
   * The dropdown calls this on every keystroke, including when the box is emptied. A blank
   * term must not run a query -- a null BigQuery client is the assertion -- and must not come
   * back as an error the UI has to handle.
   */
  @Test
  void candidates_returnsEmptyForBlankTerm() {
    ConditionLookupService service = new ConditionLookupService(null, null, HPO);

    for (String blank : new String[] {null, "", "   "}) {
      var result = service.candidates(blank);
      assertThat(result).isNotNull();
      assertThat(result.getTerm()).isEmpty();
      assertThat(result.getCandidates()).isEmpty();
    }
  }

  /** Echoed back trimmed, so a type-ahead can match a response to the keystroke it came from. */
  @Test
  void candidates_echoesTheTrimmedTerm() {
    ConditionLookupService service = new ConditionLookupService(null, null, HPO);
    assertThat(service.candidates("  ( )  ").getTerm()).isEqualTo("( )");
  }

  @Test
  void candidates_returnsEmptyWhenNoUsableTerms() {
    ConditionLookupService service = new ConditionLookupService(null, null, HPO);
    assertThat(service.candidates("( )").getCandidates()).isEmpty();
  }

  @Test
  void matchTerms_keepsTermsThatAreOnlyPartialWords() {
    // Substring matching is the point of choosing LIKE over SEARCH(): "diabet" has to survive
    // tokenization to be able to match "diabetes" in the query.
    assertThat(ConditionLookupService.matchTerms("diabet")).containsExactly("diabet");
    assertThat(List.of(ConditionLookupService.likePattern("diabet"))).containsExactly("%diabet%");
  }
}
