package org.broadinstitute.variantinterpretation.config;

import com.google.cloud.bigquery.BigQuery;
import com.google.cloud.bigquery.BigQueryOptions;
import org.broadinstitute.variantinterpretation.datasource.BigQueryProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(BigQueryProperties.class)
public class BigQueryConfig {

  /**
   * BigQuery client authenticated with Application Default Credentials: the gcloud user
   * credentials during local development, and the VM's attached service account when running
   * in Verily Workbench. Credentials are resolved lazily on the first call, so a missing or
   * expired ADC surfaces as a failed access check rather than as a failure to start up.
   */
  @Bean
  public BigQuery bigQuery(BigQueryProperties properties) {
    return BigQueryOptions.newBuilder().setProjectId(properties.billingProjectId()).build().getService();
  }
}
