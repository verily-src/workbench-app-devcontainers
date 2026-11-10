package org.broadinstitute.variantinterpretation.config;

import org.openapitools.jackson.nullable.JsonNullableModule;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Registers the module that lets Jackson (de)serialize the generated OpenAPI models' nullable
 * fields (JsonNullable<T>) as plain JSON values instead of the wrapper's own fields.
 */
@Configuration
public class JacksonConfig {

  @Bean
  public JsonNullableModule jsonNullableModule() {
    return new JsonNullableModule();
  }
}
