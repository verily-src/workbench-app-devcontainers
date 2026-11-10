package org.broadinstitute.variantinterpretation.ontology;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Optional;
import org.broadinstitute.variantinterpretation.model.HpoTerm;
import org.junit.jupiter.api.Test;

/** The pairing rules, against the trimmed ontology; the last test reads the real release. */
public class HpoLookupServiceTest {

  /** A service over the trimmed ontology in test resources, shared with the condition lookup's test. */
  public static HpoLookupService trimmed() {
    return new HpoLookupService(HpoOntologyTest.trimmed());
  }

  private static final HpoLookupService HPO = trimmed();

  private static String id(Optional<HpoTerm> term) {
    return term.map(HpoTerm::getId).orElse(null);
  }

  @Test
  void pairsAConceptNamedLikeATermExactly() {
    Optional<HpoTerm> term = HPO.match("Tetralogy of Fallot");
    assertThat(term).isPresent();
    assertThat(term.get().getId()).isEqualTo("HP:0001636");
    assertThat(term.get().getName()).isEqualTo("Tetralogy of Fallot");
    assertThat(term.get().getMatch()).isEqualTo(HpoTerm.MatchEnum.EXACT);
  }

  /** Case, punctuation and accents don't count; the normalized phrases have to agree. */
  @Test
  void ignoresCasePunctuationAndAccents() {
    assertThat(id(HPO.match("HYPERTROPHIC CARDIOMYOPATHY"))).isEqualTo("HP:0001639");
    assertThat(id(HPO.match("Tetralogy-of-Fallot."))).isEqualTo("HP:0001636");
    assertThat(id(HPO.match("Hypertróphic cardiomyopathy"))).isEqualTo("HP:0001639");
  }

  /** "Long QT syndrome" is an exact synonym of Prolonged QT interval, so the pairing is exact. */
  @Test
  void pairsOnExactSynonyms() {
    Optional<HpoTerm> term = HPO.match("Long QT syndrome");
    assertThat(id(term)).isEqualTo("HP:0001657");
    assertThat(term.get().getName()).isEqualTo("Prolonged QT interval");
    assertThat(term.get().getMatch()).isEqualTo(HpoTerm.MatchEnum.EXACT);
    // A related synonym isn't an identity: "Long Q-T syndrome" normalizes to a different phrase.
    assertThat(id(HPO.match("Long Q-T syndrome"))).isNull();
  }

  /** A term whose words all appear in the concept's name pairs as approximate: broader, and said so. */
  @Test
  void pairsABroaderTermWhoseWordsTheConceptContains() {
    Optional<HpoTerm> term = HPO.match("Familial hypercholesterolemia");
    assertThat(id(term)).isEqualTo("HP:0003124");
    assertThat(term.get().getName()).isEqualTo("Hypercholesterolemia");
    assertThat(term.get().getMatch()).isEqualTo(HpoTerm.MatchEnum.APPROXIMATE);

    assertThat(id(HPO.match("Tetralogy of Fallot, unspecified"))).isEqualTo("HP:0001636");
  }

  /** Of several contained terms the most specific (most words) wins. */
  @Test
  void prefersTheMostSpecificContainedTerm() {
    // Contains "Tetralogy of Fallot" and "Tetralogy of Fallot with pulmonary atresia".
    Optional<HpoTerm> term = HPO.match("Tetralogy of Fallot with pulmonary atresia, late sequelae");
    assertThat(id(term)).isEqualTo("HP:0012516");
    assertThat(term.get().getMatch()).isEqualTo(HpoTerm.MatchEnum.APPROXIMATE);
  }

  /** Connectives don't have to be present for a containment; the content words do. */
  @Test
  void ignoresConnectivesWhenContaining() {
    assertThat(id(HPO.match("Fallot tetralogy, repaired"))).isEqualTo("HP:0001636");
  }

  /** A short single word is too easy to contain: "Pain" shouldn't pair with everything painful. */
  @Test
  void doesNotPairOnAShortSingleWord() {
    assertThat(id(HPO.match("Chest pain"))).isNull();
    assertThat(id(HPO.match("Pain"))).as("but an exact match still is").isEqualTo("HP:9999998");
  }

  /** Nothing contained, nothing exact: no term rather than a guess. */
  @Test
  void pairsNothingRatherThanGuessing() {
    assertThat(HPO.match("Pentalogy of Fallot")).isEmpty();
    assertThat(HPO.match("Congenital heart disease")).isEmpty();
    assertThat(HPO.match("")).isEmpty();
    assertThat(HPO.match("   ")).isEmpty();
    assertThat(HPO.match(null)).isEmpty();
    assertThat(HPO.match("...")).isEmpty();
  }

  /** An obsolete term's synonym doesn't pair, even when it would match exactly. */
  @Test
  void ignoresObsoleteTerms() {
    // HP:9999999 is obsolete and carries "Tetralogy of Fallot" as a synonym; the current term wins.
    assertThat(id(HPO.match("Tetralogy of Fallot"))).isEqualTo("HP:0001636");
    assertThat(id(HPO.match("Retired cardiac term"))).isNull();
  }

  @Test
  void normalizesAndSplitsWords() {
    assertThat(HpoLookupService.normalize("  Tétralogy of Fallot, (unspecified)  ")).isEqualTo("tetralogy of fallot unspecified");
    assertThat(HpoLookupService.words("tetralogy of fallot")).containsExactlyInAnyOrder("tetralogy", "fallot");
    assertThat(HpoLookupService.words("of the")).containsExactlyInAnyOrder("of", "the");
  }

  /** The release is the ontology's; the fixture's header is read by HpoOntologyTest. */
  @Test
  void reportsTheOntologysRelease() {
    assertThat(HPO.release()).isEqualTo(HpoOntologyTest.trimmed().release()).isNotEqualTo("unknown");
  }

  /**
   * The real release, as the build puts it on the classpath: it loads, it is the release
   * build.gradle pins (handed to the test JVM as a system property, so the date lives only there),
   * and the four example conditions VIA ships pair the way the trimmed fixture says they do.
   */
  @Test
  void loadsThePinnedReleaseFromTheClasspath() {
    String pinned = System.getProperty("via.hpo.release");
    assertThat(pinned).as("via.hpo.release, set by the test task in build.gradle").isNotNull();

    HpoLookupService real = new HpoLookupService();

    assertThat(real.release()).isEqualTo(pinned.replaceFirst("^v", ""));
    assertThat(id(real.match("Tetralogy of Fallot"))).isEqualTo("HP:0001636");
    assertThat(id(real.match("Hypertrophic cardiomyopathy"))).isEqualTo("HP:0001639");
    assertThat(id(real.match("Long QT syndrome"))).isEqualTo("HP:0001657");
    assertThat(id(real.match("Familial hypercholesterolemia"))).isEqualTo("HP:0003124");
    assertThat(real.match("Familial hypercholesterolemia").get().getMatch()).isEqualTo(HpoTerm.MatchEnum.APPROXIMATE);
  }
}
