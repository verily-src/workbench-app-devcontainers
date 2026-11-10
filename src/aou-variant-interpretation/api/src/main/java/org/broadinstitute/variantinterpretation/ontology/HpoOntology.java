package org.broadinstitute.variantinterpretation.ontology;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The Human Phenotype Ontology, read from an OBO file: the terms under <i>Phenotypic
 * abnormality</i> (HP:0000118) that are still current, each with its name and exact synonyms,
 * and the release the file came from.
 *
 * <p>Only that branch is kept. The others -- modes of inheritance, clinical modifiers,
 * frequencies, blood groups -- aren't what someone means when they name a phenotype, and keeping
 * them would let "Frequent" or "Adult onset" match a condition. Obsolete terms are dropped
 * rather than followed to their replacement: an obsolete name that still matches a condition
 * is a sign the condition's own name has moved on, and a stale pairing would be presented as
 * current.
 */
public final class HpoOntology {

  /** The branch whose terms are kept. */
  public static final String PHENOTYPIC_ABNORMALITY = "HP:0000118";

  /** One current term: its id, name and exact synonyms (the OBO's {@code EXACT} scope). */
  public record Term(String id, String name, List<String> exactSynonyms) {}

  private static final Pattern SYNONYM = Pattern.compile("^\"(.*)\"\\s+(EXACT|RELATED|NARROW|BROAD)\\b");

  private final String release;
  private final Map<String, Term> terms;

  private HpoOntology(String release, Map<String, Term> terms) {
    this.release = release;
    this.terms = terms;
  }

  /** The release named in the file's {@code data-version} header, e.g. "2026-09-01"; "unknown" if absent. */
  public String release() {
    return release;
  }

  public Collection<Term> terms() {
    return terms.values();
  }

  public Term term(String id) {
    return terms.get(id);
  }

  public int size() {
    return terms.size();
  }

  /** Parses an OBO 1.2 file, as the HPO publishes it. */
  public static HpoOntology parse(InputStream obo) {
    try (BufferedReader reader = new BufferedReader(new InputStreamReader(obo, StandardCharsets.UTF_8))) {
      return parse(reader);
    } catch (IOException e) {
      throw new UncheckedIOException("Could not read the HPO file", e);
    }
  }

  private static HpoOntology parse(BufferedReader reader) throws IOException {
    String release = "unknown";
    Map<String, Stanza> stanzas = new LinkedHashMap<>();
    Stanza current = null;
    boolean inTerm = false;
    for (String line = reader.readLine(); line != null; line = reader.readLine()) {
      if (line.startsWith("[")) {
        // A new stanza; only [Term] stanzas are read, the rest ([Typedef]) are skipped.
        inTerm = line.equals("[Term]");
        current = inTerm ? new Stanza() : null;
        continue;
      }
      if (line.isEmpty()) continue;
      int colon = line.indexOf(':');
      if (colon < 0) continue;
      String tag = line.substring(0, colon);
      String value = line.substring(colon + 1).trim();
      if (current == null) {
        if (tag.equals("data-version")) release = value.replaceFirst("^hp/releases/", "");
        continue;
      }
      switch (tag) {
        case "id" -> {
          current.id = value;
          stanzas.put(value, current);
        }
        case "name" -> current.name = value;
        case "is_a" -> current.parents.add(value.split(" ")[0]);
        case "is_obsolete" -> current.obsolete = value.startsWith("true");
        case "synonym" -> {
          Matcher synonym = SYNONYM.matcher(value);
          if (synonym.find() && synonym.group(2).equals("EXACT")) current.exactSynonyms.add(synonym.group(1));
        }
        default -> {
          // def, comment, xref, alt_id, property_value, subset, consider, replaced_by: not needed.
        }
      }
    }
    return new HpoOntology(release, currentPhenotypicAbnormalities(stanzas));
  }

  /** The non-obsolete terms reachable downwards from PHENOTYPIC_ABNORMALITY, by id. */
  private static Map<String, Term> currentPhenotypicAbnormalities(Map<String, Stanza> stanzas) {
    Map<String, List<String>> children = new HashMap<>();
    for (Stanza stanza : stanzas.values()) {
      for (String parent : stanza.parents) {
        children.computeIfAbsent(parent, p -> new ArrayList<>()).add(stanza.id);
      }
    }
    Map<String, Term> kept = new LinkedHashMap<>();
    Set<String> seen = new HashSet<>();
    Deque<String> pending = new ArrayDeque<>();
    pending.push(PHENOTYPIC_ABNORMALITY);
    while (!pending.isEmpty()) {
      String id = pending.pop();
      if (!seen.add(id)) continue;
      Stanza stanza = stanzas.get(id);
      if (stanza == null) continue;
      if (!stanza.obsolete && stanza.name != null) {
        kept.put(id, new Term(id, stanza.name, List.copyOf(stanza.exactSynonyms)));
      }
      for (String child : children.getOrDefault(id, List.of())) pending.push(child);
    }
    return kept;
  }

  private static final class Stanza {
    String id;
    String name;
    boolean obsolete;
    final List<String> parents = new ArrayList<>();
    final List<String> exactSynonyms = new ArrayList<>();
  }
}
