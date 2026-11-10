package org.broadinstitute.variantinterpretation.datasource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.tuple;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.google.cloud.bigquery.Field;
import com.google.cloud.bigquery.FieldValue;
import com.google.cloud.bigquery.FieldValueList;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.QueryParameterValue;
import com.google.cloud.bigquery.StandardSQLTypeName;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.broadinstitute.variantinterpretation.model.CohortVariant;
import org.broadinstitute.variantinterpretation.model.PopulationFrequency;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class VatLookupServiceTest {

  private static final BigQueryProperties PROPERTIES =
      new BigQueryProperties("billing", "vat-project", "vat_dataset", "vat_v9", "cdr-project.cdr");

  private static final List<String> REPEATED_COLUMNS =
      List.of("consequence", "clinvar_classification", "clinvar_phenotype", "clinvar_rcv_num_stars");

  /** Every column the service selects, so a row built here has the shape a real result has. */
  private static final List<String> COLUMNS = columns();

  private static List<String> columns() {
    List<String> names = new ArrayList<>(List.of("vid", "gene_symbol", "aa_change", "consequence"));
    for (String source : List.of("gvs", "gnomad")) {
      names.add(source + "_max_subpop");
      for (String group : source.equals("gvs")
          ? List.of("max", "all", "afr", "amr", "eas", "eur", "mid", "oth", "sas")
          : List.of("max", "all", "afr", "amr", "asj", "eas", "fin", "nfe", "oth", "sas")) {
        names.add(source + "_" + group + "_af");
        names.add(source + "_" + group + "_ac");
        names.add(source + "_" + group + "_an");
      }
    }
    names.addAll(List.of("clinvar_classification", "clinvar_phenotype", "clinvar_last_updated", "clinvar_rcv_num_stars"));
    names.addAll(
        List.of(
            "splice_ai_acceptor_gain_score",
            "splice_ai_acceptor_loss_score",
            "splice_ai_donor_gain_score",
            "splice_ai_donor_loss_score",
            "LoF"));
    return names;
  }

  private static final Field[] SCHEMA =
      COLUMNS.stream()
          .map(
              name ->
                  REPEATED_COLUMNS.contains(name)
                      ? Field.newBuilder(name, StandardSQLTypeName.STRING).setMode(Field.Mode.REPEATED).build()
                      : Field.of(name, StandardSQLTypeName.STRING))
          .toArray(Field[]::new);

  private static FieldValue primitive(Object value) {
    return FieldValue.of(FieldValue.Attribute.PRIMITIVE, value == null ? null : String.valueOf(value));
  }

  /**
   * A row with the given columns set and every other one null. A repeated column takes a List,
   * whose elements may be null, as BigQuery's can.
   */
  private static FieldValueList row(Map<String, Object> values) {
    List<FieldValue> cells = new ArrayList<>();
    for (String column : COLUMNS) {
      Object value = values.get(column);
      if (REPEATED_COLUMNS.contains(column)) {
        List<FieldValue> elements =
            value == null ? List.of() : ((List<?>) value).stream().map(VatLookupServiceTest::primitive).toList();
        cells.add(FieldValue.of(FieldValue.Attribute.REPEATED, elements));
      } else {
        cells.add(primitive(value));
      }
    }
    return FieldValueList.of(cells, SCHEMA);
  }

  /** A row for a vid with the given columns, given as alternating names and values. */
  private static FieldValueList row(String vid, Object... columnsAndValues) {
    Map<String, Object> values = new HashMap<>();
    values.put("vid", vid);
    for (int i = 0; i < columnsAndValues.length; i += 2) {
      values.put((String) columnsAndValues[i], columnsAndValues[i + 1]);
    }
    return row(values);
  }

  private static CohortVariant lookupOne(FieldValueList row) {
    String vid = row.get("vid").getStringValue();
    return service(List.of(row)).lookup(List.of(vid)).get(0);
  }

  private static BigQueryService bigQuery;

  private static VatLookupService service(List<FieldValueList> rows) {
    bigQuery = mock(BigQueryService.class);
    when(bigQuery.query(any(), eq("VAT lookup"))).thenReturn(rows);
    return new VatLookupService(bigQuery, PROPERTIES);
  }

  /** No vids means no query -- a null client is the assertion -- and nothing back. */
  @Test
  void lookup_returnsNothingWithoutQueryingWhenNoVidsAreRequested() {
    assertThat(new VatLookupService(null, PROPERTIES).lookup(List.of())).isEmpty();
  }

  @Test
  void lookup_asksTheConfiguredTableForExactlyTheRequestedVids() {
    service(List.of()).lookup(List.of("1-100-A-G", "2-200-C-T"));

    ArgumentCaptor<QueryJobConfiguration.Builder> sent = ArgumentCaptor.forClass(QueryJobConfiguration.Builder.class);
    verify(bigQuery).query(sent.capture(), eq("VAT lookup"));
    QueryJobConfiguration query = sent.getValue().build();
    assertThat(query.getQuery()).contains("FROM `vat-project.vat_dataset.vat_v9`").contains("vid IN UNNEST(@vids)");
    QueryParameterValue vids = query.getNamedParameters().get("vids");
    assertThat(vids.getArrayValues()).extracting(QueryParameterValue::getValue).containsExactly("1-100-A-G", "2-200-C-T");
  }

  /**
   * The response lines up with the request, whatever order BigQuery returns rows in, and a vid
   * the VAT doesn't have is a placeholder rather than a gap: the UI shows it as "Not observed in
   * All of Us" instead of losing the row.
   */
  @Test
  void lookup_keepsRequestOrderAndPlaceholdsVidsTheVatLacks() {
    VatLookupService service =
        service(List.of(row("3-300-G-A", "gene_symbol", "LDLR"), row("1-100-A-G", "gene_symbol", "MYH7")));

    List<CohortVariant> variants = service.lookup(List.of("1-100-A-G", "2-200-C-T", "3-300-G-A"));

    assertThat(variants)
        .extracting(CohortVariant::getVariant, CohortVariant::getAnnotated, v -> v.getGene().orElse(null))
        .containsExactly(
            tuple("1-100-A-G", true, "MYH7"), tuple("2-200-C-T", false, null), tuple("3-300-G-A", true, "LDLR"));
    CohortVariant placeholder = variants.get(1);
    assertThat(placeholder.getAouPopulations()).isEmpty();
    assertThat(placeholder.getClinvarConditions()).isEmpty();
    assertThat(placeholder.getClinvarSignificance().orElse(null)).isNull();
  }

  /** A fully populated row: every column lands on the field the UI reads it from. */
  @Test
  void mapsEveryColumnOfAFullRow() {
    CohortVariant variant =
        lookupOne(
            row(
                "14-23424218-G-A",
                "gene_symbol", "MYH7",
                "aa_change", "p.Arg403Gln",
                "consequence", List.of("intron_variant", "missense_variant"),
                "gvs_max_subpop", "afr",
                "gvs_max_af", 0.0123,
                "gvs_max_ac", 12,
                "gvs_max_an", 976,
                "gvs_all_af", 0.0021,
                "gvs_all_ac", 21,
                "gvs_all_an", 10_000,
                "gvs_afr_af", 0.0123,
                "gvs_afr_ac", 12,
                "gvs_afr_an", 976,
                "gnomad_max_subpop", "nfe",
                "gnomad_max_af", 0.00031,
                "gnomad_max_ac", 9,
                "gnomad_max_an", 29_000,
                "gnomad_all_af", 0.00011,
                "gnomad_all_ac", 15,
                "gnomad_all_an", 140_000,
                "gnomad_fin_af", 0.0,
                "gnomad_fin_ac", 0,
                "gnomad_fin_an", 10_500,
                "clinvar_classification", List.of("Likely pathogenic", "Pathogenic"),
                "clinvar_phenotype", List.of("Hypertrophic cardiomyopathy", "not provided"),
                "clinvar_last_updated", "2024-02-14",
                "clinvar_rcv_num_stars", Arrays.asList(1, null, 3),
                "splice_ai_acceptor_gain_score", 0.01,
                "splice_ai_acceptor_loss_score", null,
                "splice_ai_donor_gain_score", 0.62,
                "splice_ai_donor_loss_score", 0.2,
                "LoF", "HC"));

    assertThat(variant.getVariant()).isEqualTo("14-23424218-G-A");
    assertThat(variant.getAnnotated()).isTrue();
    assertThat(variant.getGene().orElse(null)).isEqualTo("MYH7");
    assertThat(variant.getProteinChange().orElse(null)).isEqualTo("p.Arg403Gln");
    // The first VEP term with a label, skipping ones the UI has no label for.
    assertThat(variant.getConsequence().orElse(null)).isEqualTo("Missense");

    assertThat(variant.getAouSubpopulation().orElse(null)).isEqualTo(CohortVariant.AouSubpopulationEnum.AFR);
    assertThat(variant.getAouAf().orElse(null)).isEqualByComparingTo("0.0123");
    assertThat(variant.getAouAc().orElse(null)).isEqualTo(12);
    assertThat(variant.getAouAn().orElse(null)).isEqualTo(976);
    assertThat(variant.getAouAllAf().orElse(null)).isEqualByComparingTo("0.0021");
    assertThat(variant.getAouAllAc().orElse(null)).isEqualTo(21);
    assertThat(variant.getAouAllAn().orElse(null)).isEqualTo(10_000);
    // Every All of Us population is listed, in a fixed order, whether or not this row has it.
    assertThat(variant.getAouPopulations())
        .extracting(PopulationFrequency::getPopulation)
        .containsExactly("AFR", "AMR", "EAS", "EUR", "MID", "OTH", "SAS");
    assertThat(variant.getAouPopulations().get(0))
        .satisfies(
            afr -> {
              assertThat(afr.getAf().orElse(null)).isEqualByComparingTo("0.0123");
              assertThat(afr.getAc().orElse(null)).isEqualTo(12);
              assertThat(afr.getAn().orElse(null)).isEqualTo(976);
            });
    assertThat(variant.getAouPopulations().get(3).getAf().orElse(null)).as("EUR, not in the row").isNull();

    assertThat(variant.getGnomadSubpopulation().orElse(null)).isEqualTo(CohortVariant.GnomadSubpopulationEnum.NFE);
    assertThat(variant.getGnomadAf().orElse(null)).isEqualByComparingTo("0.00031");
    assertThat(variant.getGnomadAc().orElse(null)).isEqualTo(9);
    assertThat(variant.getGnomadAn().orElse(null)).isEqualTo(29_000);
    assertThat(variant.getGnomadAllAf().orElse(null)).isEqualByComparingTo("0.00011");
    assertThat(variant.getGnomadAllAc().orElse(null)).isEqualTo(15);
    assertThat(variant.getGnomadAllAn().orElse(null)).isEqualTo(140_000);
    assertThat(variant.getGnomadPopulations())
        .extracting(PopulationFrequency::getPopulation)
        .containsExactly("AFR", "AMR", "ASJ", "EAS", "FIN", "NFE", "OTH", "SAS");
    // A real zero in a covered population stays a zero, distinct from the nulls around it.
    assertThat(variant.getGnomadPopulations().get(4))
        .satisfies(
            fin -> {
              assertThat(fin.getAf().orElse(null)).isEqualByComparingTo("0");
              assertThat(fin.getAc().orElse(null)).isZero();
              assertThat(fin.getAn().orElse(null)).isEqualTo(10_500);
            });

    // ClinVar: the first classification with a mapping, the highest star rating across RCVs
    // (nulls skipped), every phenotype as listed, and the date parsed.
    assertThat(variant.getClinvarSignificance().orElse(null)).isEqualTo(CohortVariant.ClinvarSignificanceEnum.LIKELY_PATHOGENIC);
    assertThat(variant.getClinvarStars().orElse(null)).isEqualTo(3);
    assertThat(variant.getClinvarHasConflicts()).isFalse();
    assertThat(variant.getClinvarConditions()).containsExactly("Hypertrophic cardiomyopathy", "not provided");
    assertThat(variant.getClinvarLastUpdated().orElse(null)).isEqualTo(LocalDate.of(2024, 2, 14));

    // SpliceAI's headline is the max of the four deltas, nulls skipped.
    assertThat(variant.getSpliceAi().orElse(null)).isEqualByComparingTo("0.62");
    assertThat(variant.getPlof().orElse(null)).isEqualTo(CohortVariant.PlofEnum.HC);
  }

  /** A row with nothing but a vid is still an annotated variant; every figure is null, not zero. */
  @Test
  void mapsASparseRowToNullsWithoutFailing() {
    CohortVariant variant = lookupOne(row("1-100-A-G"));

    assertThat(variant.getAnnotated()).isTrue();
    assertThat(variant.getGene().orElse(null)).isNull();
    assertThat(variant.getProteinChange().orElse(null)).isNull();
    assertThat(variant.getConsequence().orElse(null)).isNull();
    assertThat(variant.getAouSubpopulation().orElse(null)).isNull();
    assertThat(variant.getAouAf().orElse(null)).isNull();
    assertThat(variant.getAouAc().orElse(null)).isNull();
    assertThat(variant.getAouAllAn().orElse(null)).isNull();
    assertThat(variant.getAouPopulations()).hasSize(7).allSatisfy(p -> assertThat(p.getAf().orElse(null)).isNull());
    assertThat(variant.getGnomadSubpopulation().orElse(null)).isNull();
    assertThat(variant.getGnomadPopulations()).hasSize(8).allSatisfy(p -> assertThat(p.getAc().orElse(null)).isNull());
    assertThat(variant.getClinvarSignificance().orElse(null)).isNull();
    assertThat(variant.getClinvarStars().orElse(null)).isNull();
    assertThat(variant.getClinvarHasConflicts()).isFalse();
    assertThat(variant.getClinvarConditions()).isEmpty();
    assertThat(variant.getClinvarLastUpdated().orElse(null)).isNull();
    assertThat(variant.getSpliceAi().orElse(null)).isNull();
    assertThat(variant.getPlof().orElse(null)).isNull();
  }

  /**
   * "Conflicting interpretations" is ClinVar's own aggregate call, not one of the five
   * significances: it maps to no significance but raises the conflicts flag, so the UI shows the
   * record without a badge. The flag isn't a distinct-count over classifications, since two RCVs
   * for different conditions can legitimately differ.
   */
  @Test
  void clinvar_conflictsComeFromTheAggregateClassification() {
    CohortVariant conflicting = lookupOne(row("1-100-A-G", "clinvar_classification", List.of("Conflicting interpretations")));
    assertThat(conflicting.getClinvarSignificance().orElse(null)).isNull();
    assertThat(conflicting.getClinvarHasConflicts()).isTrue();

    CohortVariant vus = lookupOne(row("1-100-A-G", "clinvar_classification", List.of("Uncertain significance", "Benign")));
    assertThat(vus.getClinvarSignificance().orElse(null)).isEqualTo(CohortVariant.ClinvarSignificanceEnum.VUS);
    assertThat(vus.getClinvarHasConflicts()).isFalse();
  }

  /**
   * Only the VEP terms the UI labels count, and the most severe labelled term wins whatever order
   * the VAT lists them in; a row with none of them has no consequence.
   */
  @Test
  void consequence_readsOnlyTheLabelledTerms() {
    assertThat(lookupOne(row("1-1-A-G", "consequence", List.of("upstream_gene_variant", "non_coding_transcript_exon_variant"))).getConsequence().orElse(null))
        .isNull();
    assertThat(lookupOne(row("1-1-A-G", "consequence", List.of("intron_variant", "3_prime_UTR_variant"))).getConsequence().orElse(null))
        .isEqualTo("3' UTR");
    assertThat(lookupOne(row("1-1-A-G", "consequence", List.of("inframe_deletion", "splice_region_variant"))).getConsequence().orElse(null))
        .isEqualTo("In-frame indel");
    assertThat(lookupOne(row("1-1-A-G", "consequence", List.of("splice_acceptor_variant"))).getConsequence().orElse(null))
        .isEqualTo("Splice site");
    assertThat(lookupOne(row("1-1-A-G", "consequence", List.of("missense_variant", "stop_gained"))).getConsequence().orElse(null))
        .isEqualTo("Nonsense");
  }

  /** LOFTEE's other values (OS, "other splice") aren't a call the UI shows; they read as unscored. */
  @Test
  void plof_keepsOnlyHighAndLowConfidenceCalls() {
    assertThat(lookupOne(row("1-1-A-G", "LoF", "LC")).getPlof().orElse(null)).isEqualTo(CohortVariant.PlofEnum.LC);
    assertThat(lookupOne(row("1-1-A-G", "LoF", "OS")).getPlof().orElse(null)).isNull();
  }

  /** The highest rating wins even when a null RCV comes first; all-null is no rating. */
  @Test
  void clinvarStars_takeTheHighestRatedRcv() {
    assertThat(lookupOne(row("1-1-A-G", "clinvar_rcv_num_stars", Arrays.asList(null, 2, 0))).getClinvarStars().orElse(null))
        .isEqualTo(2);
    assertThat(lookupOne(row("1-1-A-G", "clinvar_rcv_num_stars", Arrays.asList((Object) null))).getClinvarStars().orElse(null))
        .isNull();
  }

  /**
   * A subpopulation code the API's enum doesn't know reads as no subpopulation rather than
   * failing the lookup: the generated enums' fromValue returns null for an unknown value. The
   * synthetic VAT only uses known codes, so this is the one place the real VAT could differ, and
   * the row has to survive it.
   */
  @Test
  void subpopulation_outsideTheEnumReadsAsNull() {
    CohortVariant variant = lookupOne(row("1-1-A-G", "gvs_max_subpop", "xyz", "gvs_max_af", 0.5, "gnomad_max_subpop", "mde"));

    assertThat(variant.getAouSubpopulation().orElse(null)).isNull();
    assertThat(variant.getGnomadSubpopulation().orElse(null)).isNull();
    assertThat(variant.getAouAf().orElse(null)).isEqualByComparingTo("0.5");
  }

  /** A date BigQuery didn't send as YYYY-MM-DD does fail the lookup; the VAT's DATE column never should. */
  @Test
  void clinvarLastUpdated_mustBeAnIsoDate() {
    assertThatThrownBy(() -> lookupOne(row("1-1-A-G", "clinvar_last_updated", "2024-02-14 00:00:00")))
        .isInstanceOf(java.time.format.DateTimeParseException.class);
  }

  /** Frequencies keep the precision BigQuery sent, as decimals the JSON carries unchanged. */
  @Test
  void frequencies_areDecimalsOfTheValueBigQuerySent() {
    CohortVariant variant = lookupOne(row("1-1-A-G", "gvs_all_af", 4.3e-7, "gvs_all_ac", 1, "gvs_all_an", 2_325_581));

    assertThat(variant.getAouAllAf().orElse(null)).isEqualTo(BigDecimal.valueOf(4.3e-7));
    assertThat(variant.getAouAllAc().orElse(null)).isEqualTo(1);
    assertThat(variant.getAouAllAn().orElse(null)).isEqualTo(2_325_581);
  }
}
