package org.broadinstitute.variantinterpretation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.tuple;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.Table;
import com.google.cloud.bigquery.TableId;
import org.broadinstitute.variantinterpretation.controller.SystemController;
import org.broadinstitute.variantinterpretation.datasource.BigQueryProperties;
import org.broadinstitute.variantinterpretation.datasource.BigQueryService;
import org.broadinstitute.variantinterpretation.datasource.QueryUsageMeter;
import org.broadinstitute.variantinterpretation.model.BigQueryStatus;
import org.broadinstitute.variantinterpretation.model.TableStatus;
import java.util.List;
import org.broadinstitute.variantinterpretation.model.DataSourceVersion;
import org.broadinstitute.variantinterpretation.ontology.HpoLookupService;
import org.broadinstitute.variantinterpretation.ontology.HpoLookupServiceTest;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

class SystemControllerTest {

  /** The trimmed ontology; its release is what the data-sources list should report. */
  private static final HpoLookupService HPO = HpoLookupServiceTest.trimmed();

  private final BigQueryProperties properties =
      new BigQueryProperties(
          "billing-project", "test-project", "test_dataset", "v1", "cdr-project.test_cdr");

  @Test
  void bigQueryStatus_returnsAccessibleTrue_whenEveryTableIsReachable() {
    BigQuery bigQuery = mock(BigQuery.class);
    when(bigQuery.getTable(any(TableId.class))).thenReturn(mock(Table.class));

    QueryUsageMeter usage = new QueryUsageMeter();
    ResponseEntity<BigQueryStatus> response =
        new SystemController(new BigQueryService(bigQuery, usage), properties, usage, HPO).bigQueryStatus();

    assertThat(response.getStatusCode().value()).isEqualTo(200);
    assertThat(response.getBody()).isNotNull();
    assertThat(response.getBody().getAccessible()).isTrue();
    assertThat(response.getBody().getTables())
        .extracting(TableStatus::getTable)
        .containsExactly(
            "test-project.test_dataset.v1",
            "cdr-project.test_cdr.cb_criteria",
            "cdr-project.test_cdr.concept_ancestor",
            "cdr-project.test_cdr.condition_occurrence");
    assertThat(response.getBody().getTables()).allMatch(TableStatus::getAccessible);
  }

  @Test
  void bigQueryStatus_reportsEachTableSeparately() {
    BigQuery bigQuery = mock(BigQuery.class);
    when(bigQuery.getTable(any(TableId.class))).thenReturn(mock(Table.class));
    when(bigQuery.getTable(properties.vatTable())).thenReturn(null);
    when(bigQuery.getTable(properties.cdrTable("concept_ancestor")))
        .thenThrow(new RuntimeException("Access Denied"));

    QueryUsageMeter usage = new QueryUsageMeter();
    BigQueryStatus status =
        new SystemController(new BigQueryService(bigQuery, usage), properties, usage, HPO).bigQueryStatus().getBody();

    assertThat(status).isNotNull();
    assertThat(status.getAccessible()).isFalse();
    assertThat(status.getTables())
        .extracting(TableStatus::getTable, TableStatus::getAccessible, t -> t.getDetail().orElse(null))
        .containsExactly(
            tuple(
                "test-project.test_dataset.v1",
                false,
                "Table does not exist, or is not visible to user."),
            tuple("cdr-project.test_cdr.cb_criteria", true, null),
            tuple("cdr-project.test_cdr.concept_ancestor", false, "Access Denied"),
            tuple("cdr-project.test_cdr.condition_occurrence", true, null));
  }

  /** HPO is the one source that ships inside VIA, so its version comes from the ontology file. */
  @Test
  void dataSourceVersions_nameTheBundledHpoRelease() {
    List<DataSourceVersion> sources =
        new SystemController(null, null, null, HPO).dataSourceVersions().getBody();

    assertThat(sources).extracting(DataSourceVersion::getName).contains("All of Us", "gnomAD", "ClinVar", "HPO");
    DataSourceVersion hpo = sources.stream().filter(source -> source.getName().equals("HPO")).findFirst().orElseThrow();
    assertThat(hpo.getVersion()).isEqualTo(HPO.release());
    assertThat(hpo.getUrl().orElse(null)).isEqualTo("https://hpo.jax.org/");
    assertThat(hpo.getDescription().orElse(null)).contains("Phenotype terms");
  }

  /** Every source says what VIA takes from it, so the data-sources page can explain each row. */
  @Test
  void dataSourceVersions_describeEverySource() {
    List<DataSourceVersion> sources =
        new SystemController(null, null, null, HPO).dataSourceVersions().getBody();

    assertThat(sources).allSatisfy(source -> assertThat(source.getDescription().orElse("")).isNotBlank());
  }
}
