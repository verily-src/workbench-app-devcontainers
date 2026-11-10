import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { fetchProfile } from "../api/profile";
import type { ConditionConcept } from "../api/conditions";
import colors from "../libs/colors";
import * as Style from "../libs/style";
import Clickable from "../components/common/Clickable";
import AllOfUs from "../components/common/AllOfUs";
import Hero from "../components/Hero";
// import HeroSources from "../components/HeroSources";
import PhenotypeStep, { PHENOTYPE_STEP_DESCRIPTION } from "../components/PhenotypeStep";
import VariantsStep from "../components/VariantsStep";
import { SearchIcon } from "../components/icons";
import Footer from "../components/results/Footer";
import TopBar from "../components/results/TopBar";
import { isSubmitShortcut, SUBMIT_SHORTCUT_LABEL } from "../utils/submitShortcut";
import {
  overLimitMessage,
  parseVariantsText,
  resultsPath,
  VARIANTS_LIMIT,
  variantEntryStatus,
} from "../utils/variants";
import { describeAlternatives, searchConceptIds } from "../utils/phenotypes";
import { usePreference } from "../utils/preferences";
import { loadRecentSearches, type RecentSearch } from "../utils/recentSearches";
import { USE_CASES, type UseCase } from "../utils/useCases";

const CONDITION_FIELD_ID = "condition";

// The hero says what VIA is and what it reads from; the card is the form in the order it's
// filled: the variants box across the whole card, with the recent searches and the example
// searches as links beneath it while it's empty, then the phenotype step, open from the start --
// nearly every search adds one, so it isn't folded behind a click. Each step says in a line what
// it does for the search, so the hero doesn't have to. The card is the whole page: a recent
// search fills the form rather than running, so it can be changed first.
const styles = {
  // The page is a column that fills the window, so the footer sits at the bottom even when the
  // form doesn't reach it.
  page: {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
  },
  main: {
    flex: 1,
    width: "100%",
    maxWidth: 860 + 40,
    margin: "20px auto 0",
    padding: "0 20px 40px",
  },
  // Both steps in one card, so the page reads as a single search form with one action.
  card: {
    ...Style.elements.panel,
    // elements.panel clips with overflow: hidden, which would cut off the condition field's
    // dropdown at the card's edge. The footer rounds its own bottom corners instead.
    overflow: "visible",
    boxShadow: Style.shadows.raised,
  },
  cardBody: {
    padding: "20px 20px 18px",
  },
  // The second step, divided from the first by a hairline: both steps sit bare in the card, which
  // is the one container the form needs. A box around either would nest it inside the other.
  phenotype: {
    marginTop: 20,
    paddingTop: 20,
    borderTop: `1px solid ${colors.border}`,
  },
  cardFooter: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 12,
    padding: "12px 20px",
    background: colors.surface1,
    borderTop: `1px solid ${colors.border}`,
    // Inset by the card's 1px border, like StepPanel's header.
    borderBottomLeftRadius: Style.panelRadius - 1,
    borderBottomRightRadius: Style.panelRadius - 1,
  },
  status: {
    color: colors.textSecondary,
    fontSize: 12.5,
  },
  statusReady: {
    color: colors.textPrimary,
    fontWeight: 600,
  },
  statusError: {
    color: colors.textDanger,
    fontWeight: 600,
  },
  shortcut: {
    marginLeft: 8,
    color: colors.textMuted,
    fontSize: 11.5,
  },
  searchButton: {
    ...Style.buttons.primary,
    gap: 8,
    padding: "9px 22px",
    fontSize: 13,
    fontWeight: 700,
  },
} as const satisfies Record<string, CSSProperties>;

export default function SearchEntryPage() {
  const navigate = useNavigate();
  const [variants, setVariants] = useState("");
  const [phenotypes, setPhenotypes] = useState<ConditionConcept[]>([]);
  const [userEmail, setUserEmail] = useState("");
  const [recentSearches] = useState(loadRecentSearches);
  const [demoMode] = usePreference("demoMode");

  useEffect(() => {
    fetchProfile()
      .then((profile) => setUserEmail(profile.userEmail))
      .catch((err: Error) => console.error("Failed to load profile", err));
  }, []);

  const { count: variantCount, overLimit, canSearch } = variantEntryStatus(variants, VARIANTS_LIMIT);

  function fillExample(example: UseCase) {
    setVariants(example.variants.join("\n"));
    setPhenotypes([example.condition]);
  }

  function fillRecent(search: RecentSearch) {
    setVariants(search.variants.join("\n"));
    // History from before the estimate was kept has none; the chip shows that as unknown.
    setPhenotypes(
      search.conditions.map((condition) => ({
        ...condition,
        estimatedParticipantCount: condition.estimatedParticipantCount ?? null,
      })),
    );
  }

  function handleSearch() {
    navigate(resultsPath(parseVariantsText(variants), searchConceptIds(phenotypes)));
  }

  return (
    <div style={styles.page}>
      <TopBar userEmail={userEmail} />
      <Hero
        title={
          <>
            <AllOfUs /> Variant Interpretation
          </>
        }
        subtitle={
          <>
            See how often your candidate variants appear in <AllOfUs />, overall and in participants with the
            conditions you choose.
          </>
        }
        // TODO: decide whether the data source versions belong in the hero. HeroSources renders them
        // as a line under the subtitle, fetched from /api/sources; the settings dialog lists them too.
        // facts={<HeroSources />}
      />
      <main style={styles.main}>
        <section
          style={styles.card}
          aria-label="Search"
          onKeyDown={(event) => {
            if (!isSubmitShortcut(event)) return;
            event.preventDefault();
            if (canSearch) handleSearch();
          }}
        >
          <div style={styles.cardBody}>
            <VariantsStep
              value={variants}
              onChange={setVariants}
              limit={VARIANTS_LIMIT}
              minHeight={160}
              appearance="plain"
              numbered
              description={
                <>
                  Enter the variants you're interpreting. Each is looked up across the entire <AllOfUs /> cohort.
                </>
              }
              examples={demoMode ? USE_CASES : []}
              onUseExample={fillExample}
              recentSearches={recentSearches}
              onUseRecentSearch={fillRecent}
            />
            <div style={styles.phenotype}>
              <PhenotypeStep
                id={CONDITION_FIELD_ID}
                picked={phenotypes}
                onPick={(concept) => setPhenotypes((current) => [...current, concept])}
                onRemove={(conceptId) =>
                  setPhenotypes((current) => current.filter((concept) => concept.conceptId !== conceptId))
                }
                appearance="plain"
                numbered
                description={PHENOTYPE_STEP_DESCRIPTION}
              />
            </div>
          </div>

          <div style={styles.cardFooter}>
            {/* Says why Search is disabled, since the disabled button itself takes no pointer events. */}
            <p style={styles.status} aria-live="polite">
              {overLimit ? (
                <span style={styles.statusError}>{overLimitMessage(variantCount, VARIANTS_LIMIT)}</span>
              ) : variantCount === 0 ? (
                "Enter at least one variant to search."
              ) : (
                <>
                  <span style={styles.statusReady}>
                    {variantCount} variant{variantCount === 1 ? "" : "s"} ready
                  </span>
                  {phenotypes.length > 0 &&
                    ` · filtered by ${describeAlternatives(phenotypes.map((phenotype) => phenotype.name))}`}
                  <span style={styles.shortcut}>{SUBMIT_SHORTCUT_LABEL} to search</span>
                </>
              )}
            </p>
            <Clickable
              style={styles.searchButton}
              hoverStyle={Style.buttons.primaryHover}
              disabledStyle={Style.buttons.disabled}
              disabled={!canSearch}
              onClick={handleSearch}
            >
              <SearchIcon size={16} aria-hidden="true" style={{ flexShrink: 0 }} />
              Search
            </Clickable>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
