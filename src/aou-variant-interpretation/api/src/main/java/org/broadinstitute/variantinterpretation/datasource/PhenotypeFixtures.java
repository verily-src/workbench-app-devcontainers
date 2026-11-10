package org.broadinstitute.variantinterpretation.datasource;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * Curated phenotype-matched data for the demo use cases, which MockPhenotypeData serves in place
 * of its made-up numbers when a search's condition is one of them.
 *
 * <p>Still synthetic -- there's no genotype-level data to compute the real thing from -- but
 * written per use case so the phenotype-matched panels tell the same story as the variants picked
 * for it. Generated, with the rest of the use case data, by
 * data/synthetic/generators/generate_use_case_fixtures.py; see data/README.md.
 */
@Component
public class PhenotypeFixtures {

  private static final Logger log = LoggerFactory.getLogger(PhenotypeFixtures.class);

  static final String RESOURCE = "fixtures/phenotype_use_cases.json";

  /** One group of the ancestry or age breakdown. */
  public record Group(String label, int count) {}

  /** A use case's condition: who matched it, and each curated variant's counts among them. */
  public record UseCase(
      long conceptId,
      int participants,
      List<Group> ancestry,
      List<Group> age,
      Map<String, MockPhenotypeData.CuratedCounts> variants) {}

  private final Map<Long, UseCase> byConcept;

  // Its own mapper rather than an injected one: Spring Boot 4 configures only a Jackson 3 mapper,
  // and reading this bundled file needs none of the app's Jackson configuration anyway.
  public PhenotypeFixtures() {
    this(load(new ObjectMapper()));
  }

  /** For tests: fixtures given directly instead of read from the classpath. */
  PhenotypeFixtures(List<UseCase> useCases) {
    this.byConcept = useCases.stream().collect(Collectors.toMap(UseCase::conceptId, Function.identity()));
  }

  private static List<UseCase> load(ObjectMapper objectMapper) {
    ClassPathResource resource = new ClassPathResource(RESOURCE);
    if (!resource.exists()) {
      return List.of();
    }
    try (InputStream in = resource.getInputStream()) {
      return objectMapper.readValue(in, new TypeReference<>() {});
    } catch (IOException e) {
      throw new IllegalStateException("Couldn't read " + RESOURCE, e);
    }
  }

  /**
   * The use case for a search's resolved conditions: {@link #forCondition} when exactly one
   * resolved, and nothing otherwise. A use case is written for one condition's participants; a
   * search over several conditions matches a union those numbers don't describe, so it gets the
   * made-up ones, scaled to the union count.
   */
  public Optional<UseCase> forConditions(List<Long> conceptIds, int participants) {
    if (conceptIds.size() != 1) {
      return Optional.empty();
    }
    return forCondition(conceptIds.get(0), participants);
  }

  /**
   * The use case for this condition, if there is one and it was written for the participant count
   * the condition tables actually return. A mismatch means the fixture and the loaded tables are
   * from different generator runs, and its breakdowns wouldn't add up to the count shown beside
   * them -- so it's ignored, and the made-up numbers are used instead.
   */
  public Optional<UseCase> forCondition(long conceptId, int participants) {
    UseCase useCase = byConcept.get(conceptId);
    if (useCase == null) {
      return Optional.empty();
    }
    if (useCase.participants() != participants) {
      log.warn(
          "Ignoring the phenotype fixture for concept {}: written for {} participants, but the condition tables"
              + " match {}. Regenerate and reload the synthetic data.",
          conceptId, useCase.participants(), participants);
      return Optional.empty();
    }
    return Optional.of(useCase);
  }
}
