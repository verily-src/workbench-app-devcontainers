package org.broadinstitute.variantinterpretation.ontology;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Stream;
import org.broadinstitute.variantinterpretation.model.HpoTerm;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

/**
 * Pairs a condition concept's name with an HPO term.
 *
 * <p>VIA has no cross-reference between the All of Us condition vocabulary and HPO (the HPO
 * release carries no SNOMED or UMLS references), so the pairing is lexical, on the concept's
 * name rather than on what the user typed: the same concept always gets the same term, and the
 * term can be shown at the moment the concept is picked. Two tiers, in order:
 *
 * <ol>
 *   <li><b>Exact.</b> The name, normalized, equals a term's name or one of its exact synonyms.
 *       "Long QT syndrome" is an exact synonym of <i>Prolonged QT interval</i>, so it lands there.
 *   <li><b>Approximate.</b> Every word of some term's name (or exact synonym) appears in the
 *       concept's name: the term is a broader phrase the condition contains, e.g.
 *       <i>Hypercholesterolemia</i> for "Familial hypercholesterolemia", or <i>Tetralogy of
 *       Fallot</i> for "Tetralogy of Fallot, unspecified". The term with the most words wins, so
 *       the most specific such phrase is chosen; a single-word term has to be at least five
 *       letters, so "Pain" or "Mass" inside another word's neighborhood doesn't pair with
 *       everything.
 * </ol>
 *
 * <p>Anything else is no term. A wrong HPO code beside a condition is worse than none, so the
 * matcher is built to say nothing rather than guess; a looser, scored match (an in-process
 * search index) is the next step if this leaves too many conditions unpaired.
 */
@Service
public class HpoLookupService {

  private static final Logger log = LoggerFactory.getLogger(HpoLookupService.class);

  /** Where the Gradle build puts the pinned release; see build.gradle's downloadHpo. */
  static final String RESOURCE = "hpo/hp.obo";

  /** Connectives that carry no meaning for the word-containment tier. */
  private static final Set<String> STOP_WORDS = Set.of("of", "the", "and", "or", "with", "in", "to", "for", "by", "on", "at", "as");

  /** Shortest single word allowed to pair a term on its own in the approximate tier. */
  private static final int MIN_SINGLE_WORD_LENGTH = 5;

  private final HpoOntology ontology;
  /** Normalized name or exact synonym -> the term. First term in file order wins a collision. */
  private final Map<String, HpoOntology.Term> byPhrase = new HashMap<>();
  /** Every phrase as its word set, for the containment tier. */
  private final List<Phrase> phrases = new ArrayList<>();

  private record Phrase(Set<String> words, HpoOntology.Term term) {}

  /** The production service, over the release the build bundled; tests pass an ontology instead. */
  @Autowired
  public HpoLookupService() {
    this(load());
  }

  public HpoLookupService(HpoOntology ontology) {
    this.ontology = ontology;
    for (HpoOntology.Term term : ontology.terms()) {
      index(term.name(), term);
      for (String synonym : term.exactSynonyms()) index(synonym, term);
    }
    log.info("HPO {} loaded: {} phenotypic abnormality terms, {} names and synonyms", ontology.release(), ontology.size(), byPhrase.size());
  }

  private static HpoOntology load() {
    try (InputStream obo = new ClassPathResource(RESOURCE).getInputStream()) {
      return HpoOntology.parse(obo);
    } catch (IOException e) {
      throw new UncheckedIOException("The HPO file is missing from the classpath at " + RESOURCE, e);
    }
  }

  private void index(String phrase, HpoOntology.Term term) {
    String normalized = normalize(phrase);
    if (normalized.isEmpty()) return;
    byPhrase.putIfAbsent(normalized, term);
    Set<String> words = words(normalized);
    if (!words.isEmpty()) phrases.add(new Phrase(words, term));
  }

  /** The release of the ontology in use, for the data-sources list. */
  public String release() {
    return ontology.release();
  }

  /** The HPO term for a condition concept's name, if one pairs with it; see the class comment. */
  public Optional<HpoTerm> match(String conditionName) {
    if (conditionName == null) return Optional.empty();
    String normalized = normalize(conditionName);
    if (normalized.isEmpty()) return Optional.empty();

    HpoOntology.Term exact = byPhrase.get(normalized);
    if (exact != null) return Optional.of(toHpoTerm(exact, HpoTerm.MatchEnum.EXACT));

    Set<String> words = words(normalized);
    // Most words wins. Among phrases with the same number of words (two orderings of the same
    // words are one set here, so they tie), the lowest id wins: reverseOrder inside max picks the
    // smallest, so the choice is deterministic rather than file order.
    return phrases.stream()
        .filter(phrase -> words.containsAll(phrase.words()))
        .filter(phrase -> phrase.words().size() > 1 || phrase.words().iterator().next().length() >= MIN_SINGLE_WORD_LENGTH)
        .max(Comparator.comparingInt((Phrase phrase) -> phrase.words().size()).thenComparing(phrase -> phrase.term().id(), Comparator.reverseOrder()))
        .map(phrase -> toHpoTerm(phrase.term(), HpoTerm.MatchEnum.APPROXIMATE));
  }

  private static HpoTerm toHpoTerm(HpoOntology.Term term, HpoTerm.MatchEnum match) {
    return new HpoTerm().id(term.id()).name(term.name()).match(match);
  }

  /**
   * Lower case, accents stripped, punctuation turned to spaces and runs of space collapsed:
   * "Tetralogy of Fallot, unspecified" and "tetralogy of fallot unspecified" are the same phrase.
   */
  static String normalize(String text) {
    String folded = Normalizer.normalize(text, Normalizer.Form.NFKD).replaceAll("\\p{M}+", "");
    return folded.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", " ").trim();
  }

  /** The phrase's words without connectives; the connectives alone if there's nothing else. */
  static Set<String> words(String normalized) {
    List<String> tokens = Stream.of(normalized.split(" ")).filter(token -> !token.isEmpty()).toList();
    Set<String> kept = new HashSet<>();
    for (String token : tokens) if (!STOP_WORDS.contains(token)) kept.add(token);
    return kept.isEmpty() ? new HashSet<>(tokens) : kept;
  }
}
