package org.broadinstitute.variantinterpretation.ontology;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

/**
 * The OBO reader, against a trimmed copy of the real release (src/test/resources/hpo) and a few
 * hand-written stanzas. The full release is read once by HpoLookupServiceTest's smoke test.
 */
class HpoOntologyTest {

  static HpoOntology trimmed() {
    try (InputStream obo = HpoOntologyTest.class.getResourceAsStream("/hpo/hp-trimmed.obo")) {
      return HpoOntology.parse(obo);
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  private static HpoOntology parse(String obo) {
    return HpoOntology.parse(new ByteArrayInputStream(obo.getBytes(StandardCharsets.UTF_8)));
  }

  @Test
  void readsTheReleaseFromTheHeader() {
    assertThat(trimmed().release()).isEqualTo("2026-09-01");
    assertThat(parse("format-version: 1.2\n\n[Term]\nid: HP:0000118\nname: Phenotypic abnormality\n").release()).isEqualTo("unknown");
  }

  /** Only the Phenotypic abnormality branch: the root, modes of inheritance and typedefs are left out. */
  @Test
  void keepsOnlyTheCurrentPhenotypicAbnormalities() {
    HpoOntology ontology = trimmed();

    assertThat(ontology.term("HP:0000118").name()).isEqualTo("Phenotypic abnormality");
    assertThat(ontology.term("HP:0001636").name()).isEqualTo("Tetralogy of Fallot");
    // Reached through a chain of is_a parents, not just a direct child of the branch.
    assertThat(ontology.term("HP:0012516").name()).isEqualTo("Tetralogy of Fallot with pulmonary atresia");
    assertThat(ontology.term("HP:0000001")).as("the root").isNull();
    assertThat(ontology.term("HP:0000005")).as("Mode of inheritance").isNull();
    assertThat(ontology.term("HP:9999999")).as("obsolete, even though it sits in the branch").isNull();
    assertThat(ontology.term("HP:0000057")).as("obsolete and orphaned").isNull();
    assertThat(ontology.terms()).allSatisfy(term -> assertThat(term.name()).doesNotStartWith("obsolete"));
  }

  /** Exact synonyms are kept with the term; related, narrow and broad ones are not. */
  @Test
  void keepsExactSynonymsOnly() {
    HpoOntology.Term prolongedQt = trimmed().term("HP:0001657");
    assertThat(prolongedQt.name()).isEqualTo("Prolonged QT interval");
    assertThat(prolongedQt.exactSynonyms()).contains("Long QT syndrome").doesNotContain("Long Q-T syndrome");
  }

  @Test
  void readsSeveralParentsAndSynonymTypes() {
    HpoOntology ontology =
        parse(
            """
            format-version: 1.2
            data-version: hp/releases/2030-01-01

            [Term]
            id: HP:0000118
            name: Phenotypic abnormality

            [Term]
            id: HP:0000002
            name: Other branch

            [Term]
            id: HP:0000003
            name: Two parents
            synonym: "Lay name" EXACT layperson []
            synonym: "Broader" BROAD []
            is_a: HP:0000002 ! Other branch
            is_a: HP:0000118 ! Phenotypic abnormality

            [Typedef]
            id: part_of
            name: part of
            """);

    assertThat(ontology.release()).isEqualTo("2030-01-01");
    assertThat(ontology.size()).isEqualTo(2);
    assertThat(ontology.term("HP:0000003").exactSynonyms()).containsExactly("Lay name");
  }

  @Test
  void failsLoudlyOnAnUnreadableStream() {
    InputStream broken =
        new InputStream() {
          @Override
          public int read() throws IOException {
            throw new IOException("gone");
          }
        };
    assertThatThrownBy(() -> HpoOntology.parse(broken)).isInstanceOf(UncheckedIOException.class);
  }
}
