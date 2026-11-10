package org.broadinstitute.variantinterpretation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.QueryJobConfiguration;
import com.google.cloud.bigquery.TableId;
import com.google.cloud.bigquery.TableResult;
import java.util.List;
import org.broadinstitute.variantinterpretation.datasource.BigQueryProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

/**
 * The one test that starts the application: the context wires, the bigquery.* properties bind into
 * BigQueryProperties, and the generated models serialize the way the spec says. The last matters
 * most: the models use JsonNullable, and a null field has to come out as JSON null (which the UI
 * keys on) rather than as the wrapper's own shape, which depends on JacksonConfig's module being
 * picked up by the mapper Spring Boot actually uses. BigQuery itself is a mock that returns no rows.
 */
@SpringBootTest(
    properties = {
      "bigquery.billing-project-id=billing-project",
      "bigquery.vat-project-id=vat-project",
      "bigquery.vat-dataset-id=vat_dataset",
      "bigquery.vat-table-id=vat_v9",
      "bigquery.cdr=cdr-project.test_cdr",
      "WORKBENCH_USER_EMAIL=someone@example.org",
    })
class ApplicationSmokeTest {

  @Autowired private WebApplicationContext context;
  @Autowired private BigQueryProperties properties;
  @MockitoBean private BigQuery bigQuery;

  private MockMvc mvc;

  @BeforeEach
  void setUp() throws InterruptedException {
    mvc = MockMvcBuilders.webAppContextSetup(context).build();
    TableResult empty = mock(TableResult.class);
    when(empty.iterateAll()).thenReturn(List.of());
    when(empty.getJobId()).thenReturn(null);
    when(bigQuery.query(any(QueryJobConfiguration.class))).thenReturn(empty);
  }

  @Test
  void bindsTheBigQueryProperties() {
    assertThat(properties.billingProjectId()).isEqualTo("billing-project");
    assertThat(properties.vatTable()).isEqualTo(TableId.of("vat-project", "vat_dataset", "vat_v9"));
    assertThat(properties.cdrTable("cb_criteria")).isEqualTo(TableId.of("cdr-project", "test_cdr", "cb_criteria"));
  }

  /** A search with no condition and a vid the VAT lacks: the response's nullable fields are JSON nulls. */
  @Test
  void searchSerializesNullableFieldsAsNull() throws Exception {
    String body =
        mvc.perform(get("/api/search").param("variants", "1-100-A-G"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.searchSummary.variantsEnteredCount").value(1))
            .andExpect(jsonPath("$.searchSummary.variantsLimit").value(50))
            .andExpect(jsonPath("$.conditionSearch").value(nullValue()))
            .andExpect(jsonPath("$.cohortVariants[0].variant").value("1-100-A-G"))
            .andExpect(jsonPath("$.cohortVariants[0].annotated").value(false))
            // A nullable the code set to null is a JSON null; one it never set is left out.
            .andExpect(jsonPath("$.cohortVariants[0].gene").doesNotExist())
            .andExpect(jsonPath("$.ancestryBreakdown").isEmpty())
            .andExpect(jsonPath("$.filteredVariants").isEmpty())
            .andReturn()
            .getResponse()
            .getContentAsString();

    // The nullable wrapper itself must never leak into the JSON.
    assertThat(body).contains("\"conditionSearch\":null").doesNotContain("\"present\"");
  }

  /** The search above was metered: one request, one query it couldn't get statistics for. */
  @Test
  void usageReportsTheRequestsThatQueried() throws Exception {
    mvc.perform(get("/api/search").param("variants", "2-200-C-T")).andExpect(status().isOk());

    mvc.perform(get("/api/usage"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.searches[0].kind").value("search"))
        .andExpect(jsonPath("$.searches[0].variants[0]").value("2-200-C-T"))
        .andExpect(jsonPath("$.searches[0].phenotypes").isEmpty())
        .andExpect(jsonPath("$.searches[0].term").value(nullValue()))
        .andExpect(jsonPath("$.searches[0].queries[0].name").value("VAT lookup"))
        .andExpect(jsonPath("$.since").isString());
  }

  @Test
  void profileReportsTheWorkbenchUser() throws Exception {
    mvc.perform(get("/api/profile")).andExpect(status().isOk()).andExpect(jsonPath("$.userEmail").value("someone@example.org"));
  }

  /** A blank term never reaches BigQuery and is still a 200 with no candidates. */
  @Test
  void conditionLookupWithABlankTermIsEmpty() throws Exception {
    mvc.perform(get("/api/condition").param("condition", "  "))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.term").value(""))
        .andExpect(jsonPath("$.candidates").isEmpty());
  }
}
