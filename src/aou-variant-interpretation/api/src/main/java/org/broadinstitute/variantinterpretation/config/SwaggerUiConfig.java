package org.broadinstitute.variantinterpretation.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.ViewControllerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Serves Swagger UI at /swagger-ui, reading the hand-written api.yaml directly rather than a
 * spec reconstructed from annotations. The spec is the source of truth for the generated
 * server interfaces, so browsing it here shows exactly what the code was generated from.
 */
@Configuration
public class SwaggerUiConfig implements WebMvcConfigurer {

  @Override
  public void addResourceHandlers(ResourceHandlerRegistry registry) {
    // Not under classpath:/static/, which the Docker build overwrites with the built frontend.
    registry.addResourceHandler("/swagger-ui/**").addResourceLocations("classpath:/swagger-ui/");
    registry.addResourceHandler("/openapi/**").addResourceLocations("classpath:/openapi/");
  }

  @Override
  public void addViewControllers(ViewControllerRegistry registry) {
    // The static resource handler won't serve a directory, so /swagger-ui alone would 404.
    registry.addRedirectViewController("/swagger-ui", "/swagger-ui/index.html");
  }
}
