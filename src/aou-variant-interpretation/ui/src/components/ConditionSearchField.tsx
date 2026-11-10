import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { fetchConditionCandidates } from "../api/conditions";
import type { ConditionConcept } from "../api/conditions";
import colors from "../libs/colors";
import { useFocus, useHoveredKey } from "../libs/hooks";
import * as Style from "../libs/style";
import { formatInt } from "../utils/format";
import { describeHpo } from "../utils/hpo";
import { UserIcon } from "./icons";

/**
 * Below this we don't query at all. Matching is substring-based, so one or two characters pull
 * in near-anything -- "te" matches diabetes as readily as tetralogy. Three is where the list
 * starts being a shortlist rather than a dump.
 */
const MIN_QUERY_LENGTH = 3;

/** Long enough that ordinary typing produces one request per word, not per letter. */
const DEBOUNCE_MS = 1000;

/**
 * Rows shown before the list scrolls. The next row is cut off halfway, so it's evident there's
 * more below -- a list that ends exactly on a row boundary reads as complete.
 */
const VISIBLE_OPTIONS = 5;

const styles = {
  wrap: {
    position: "relative",
  },
  listbox: {
    position: "absolute",
    top: "calc(100% + 4px)",
    left: 0,
    right: 0,
    zIndex: 10,
    // Replaced by a measured height once the options render (see useLayoutEffect below); this is
    // 5.5 single-line rows, for the first paint.
    maxHeight: 175,
    margin: 0,
    padding: 4,
    overflowY: "auto",
    listStyle: "none",
    background: colors.surface2,
    border: `1px solid ${colors.borderStrong}`,
    borderRadius: Style.radius,
    boxShadow: Style.shadows.raised,
  },
  option: {
    display: "flex",
    // Center, not baseline: the estimate pill leads with an icon, which has no text baseline,
    // so baseline alignment would line the row up on the icon's bottom edge.
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "7px 9px",
    borderRadius: 6,
    cursor: "pointer",
  },
  optionActive: {
    background: colors.bgAccent,
  },
  optionName: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    minWidth: 0,
    color: colors.textBody,
    fontSize: 12.5,
    lineHeight: 1.35,
  },
  optionNameText: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  /** The HPO id paired with the concept, in mono and quiet: a cross-reference, not the choice itself. */
  hpo: {
    flexShrink: 0,
    color: colors.textSecondary,
    fontFamily: Style.monoFamily,
    fontSize: 10.5,
    fontWeight: 600,
    cursor: "help",
  },
  /**
   * The estimate, not the real cohort size -- /api/search returns the actual count for a
   * concept, and the two differ. Kept visually quiet so it reads as a sorting cue; the tooltip
   * carries the explanation.
   */
  estimate: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    flexShrink: 0,
    padding: "3px 7px",
    borderRadius: 999,
    background: colors.bgAccent,
    color: colors.textPrimary,
    fontFamily: Style.monoFamily,
    fontSize: 11,
    fontWeight: 600,
    lineHeight: 1,
    whiteSpace: "nowrap",
    cursor: "help",
  },
  /** On the highlighted row, whose background is the pill's own bgAccent. */
  estimateOnActive: {
    background: colors.surface2,
  },
  estimateIcon: {
    display: "block",
    flexShrink: 0,
    color: colors.textAccent,
  },
  status: {
    padding: "8px 9px",
    color: colors.textMuted,
    fontSize: 12,
  },
  error: {
    marginTop: 6,
    color: colors.textDanger,
    fontSize: 11.5,
  },
} as const satisfies Record<string, CSSProperties>;

const EXACT_COUNT_NOTE = "The exact count is calculated when you search.";

/**
 * How a concept's participant estimate is shown: the number beside a person icon, with the
 * explanation in a tooltip, plus a spoken form for screen readers, which don't get the icon.
 * est_count is nullable, and can be -1, in the real table; both mean there's no estimate.
 */
export function describeEstimate(estimate: number | null): { label: string; tooltip: string; spoken: string } {
  if (estimate === null || estimate < 0) {
    return {
      label: "—",
      tooltip: `No participant estimate for this condition. ${EXACT_COUNT_NOTE}`,
      spoken: "no participant estimate",
    };
  }
  const count = formatInt(estimate);
  return {
    label: `~${count}`,
    tooltip: `Estimated participants with this condition, from the All of Us Cohort Builder. ${EXACT_COUNT_NOTE}`,
    spoken: `about ${count} participants`,
  };
}

function Estimate({ estimate, onActiveRow = false }: { estimate: number | null; onActiveRow?: boolean }) {
  const { label, tooltip } = describeEstimate(estimate);
  return (
    <span style={{ ...styles.estimate, ...(onActiveRow ? styles.estimateOnActive : undefined) }} title={tooltip}>
      <UserIcon size={11} style={styles.estimateIcon} aria-hidden="true" />
      <span style={Style.elements.trimmedText}>{label}</span>
    </span>
  );
}

interface ConditionSearchFieldProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  /**
   * Fired when a concept is picked from the list, so the caller can keep its id. Always fires
   * immediately after the onChange carrying the concept's name -- see applySelection.
   */
  onSelect?: (concept: ConditionConcept) => void;
  /** Concepts to leave out of the list, e.g. ones already picked. */
  excludeConceptIds?: number[];
  placeholder?: string;
}

/**
 * Free-text condition search with a type-ahead dropdown, backed by /api/condition.
 *
 * The list is candidates only: concept names ranked by All of Us's participant estimate. It
 * deliberately does not count participants -- that's the expensive half of the pipeline, and
 * only worth running once a concept has actually been chosen.
 */
export default function ConditionSearchField({
  id,
  value,
  onChange,
  onSelect,
  excludeConceptIds,
  placeholder,
}: ConditionSearchFieldProps) {
  const [allCandidates, setCandidates] = useState<ConditionConcept[]>([]);
  // Filtered at render rather than when stored, so a pick made while a list is held (the
  // caller keeps the field open for the next one) drops out of it straight away.
  const candidates = excludeConceptIds?.length
    ? allCandidates.filter((concept) => !excludeConceptIds.includes(concept.conceptId))
    : allCandidates;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const { focused, focusProps } = useFocus();
  const { hoveredKey, hoverProps } = useHoveredKey<number>();
  const listboxRef = useRef<HTMLUListElement>(null);
  const listboxId = `${useId()}-listbox`;
  const [listboxMaxHeight, setListboxMaxHeight] = useState<number | undefined>(undefined);

  // Set while applying a pick, to stop the effect below from firing a fresh query for the name
  // we just wrote into the field -- which would reopen the list the user just dismissed.
  const justSelected = useRef(false);
  // Bumped to re-run the lookup for the text already in the field, when there's no list to
  // reopen: text that was in the field before its query could run.
  const [lookupRequest, setLookupRequest] = useState(0);
  // The term the current candidates are for, so reopening a list that came back empty doesn't
  // repeat a query whose answer is already known.
  const lookedUpTerm = useRef<string | null>(null);

  const query = value.trim();

  useEffect(() => {
    if (justSelected.current) {
      justSelected.current = false;
      return;
    }
    if (query.length < MIN_QUERY_LENGTH) {
      setCandidates([]);
      setLoading(false);
      setError(false);
      return;
    }

    // Abort rather than just ignore the result: a fast typist can otherwise leave a dozen
    // queries in flight, and BigQuery is charged per query, not per rendered result.
    const controller = new AbortController();
    setLoading(true);
    const timer = window.setTimeout(() => {
      fetchConditionCandidates(query, controller.signal)
        .then((result) => {
          // The backend echoes the term back, so a response that outran a newer one can be
          // recognised and dropped instead of overwriting fresher results.
          if (result.term !== query) {
            return;
          }
          lookedUpTerm.current = result.term;
          setCandidates(result.candidates);
          setError(false);
          setActiveIndex(-1);
          setOpen(true);
        })
        .catch((err: Error) => {
          if (err.name === "AbortError") {
            return;
          }
          setCandidates([]);
          setError(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setLoading(false);
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, lookupRequest]);

  // Arrowing past the last visible row would otherwise move the highlight out of the
  // listbox's scroll area, leaving the user driving a selection they can't see. "nearest"
  // scrolls only when the option is actually out of view, so it doesn't jump on every keypress.
  useEffect(() => {
    if (activeIndex < 0) {
      return;
    }
    const option = listboxRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    // Guarded: jsdom doesn't implement scrollIntoView.
    option?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex]);

  // Measured rather than computed from the row style: long condition names wrap onto a second
  // line, so rows aren't a fixed height. Layout effect so the list never paints at the wrong size.
  useLayoutEffect(() => {
    const cutoff = listboxRef.current?.querySelectorAll<HTMLElement>('[role="option"]')[VISIBLE_OPTIONS];
    if (!cutoff) {
      setListboxMaxHeight(undefined);
      return;
    }
    // offsetTop is from the listbox's padding edge; border-box sizing also counts its border.
    const border = listboxRef.current!.offsetHeight - listboxRef.current!.clientHeight;
    setListboxMaxHeight(cutoff.offsetTop + cutoff.offsetHeight / 2 + border);
  }, [candidates, open, focused]);

  function applySelection(concept: ConditionConcept) {
    justSelected.current = true;
    setOpen(false);
    setActiveIndex(-1);
    // Order matters. PhenotypeStep clears the field in onSelect, so onChange has to fire
    // first or the name would be written back over the cleared field.
    onChange(concept.name);
    onSelect?.(concept);
  }

  /**
   * Brings the list back after it was closed, so a pick can be changed without retyping. Runs
   * on click as well as focus: after a pick the field keeps focus, so clicking back into it
   * fires no focus event.
   */
  function reopen() {
    if (open) {
      return;
    }
    setOpen(true);
    if (
      candidates.length === 0 &&
      !loading &&
      query.length >= MIN_QUERY_LENGTH &&
      lookedUpTerm.current !== query
    ) {
      // Set here rather than left to the effect, so the list opens on "Searching…" instead
      // of flashing the empty state first.
      setLoading(true);
      setLookupRequest((current) => current + 1);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      // Claimed only when there's a list to close, so an Escape that has nothing to do here
      // still reaches whatever the field sits in, e.g. the edit-search popover, which closes.
      if (showListbox) {
        event.preventDefault();
      }
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (!open || candidates.length === 0) {
      // ArrowDown reopens a list that was dismissed, without needing to retype.
      if (event.key === "ArrowDown" && candidates.length > 0) {
        event.preventDefault();
        setOpen(true);
        setActiveIndex(0);
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => (current + 1) % candidates.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => (current <= 0 ? candidates.length - 1 : current - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      // Only swallow Enter when it's choosing something; otherwise it should still submit.
      event.preventDefault();
      applySelection(candidates[activeIndex]);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  const showListbox = open && focused && query.length >= MIN_QUERY_LENGTH;
  const showEmpty = showListbox && !loading && !error && candidates.length === 0;

  return (
    <div style={styles.wrap}>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={showListbox && candidates.length > 0}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined}
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        style={{ ...Style.inputs.text, ...(focused ? Style.inputs.focused : undefined) }}
        {...focusProps}
        onFocus={() => {
          focusProps.onFocus();
          reopen();
        }}
        onClick={reopen}
      />

      {showListbox && (candidates.length > 0 || loading || showEmpty) && (
        <ul
          id={listboxId}
          ref={listboxRef}
          role="listbox"
          aria-label="Matching conditions"
          style={{ ...styles.listbox, ...(listboxMaxHeight ? { maxHeight: listboxMaxHeight } : undefined) }}
        >
          {loading && candidates.length === 0 && (
            <li style={styles.status} role="presentation">
              Searching…
            </li>
          )}
          {showEmpty && (
            <li style={styles.status} role="presentation">
              No matching conditions
            </li>
          )}
          {candidates.map((concept, index) => (
            <li
              key={concept.conceptId}
              id={`${listboxId}-option-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              aria-label={`${concept.name}, ${describeEstimate(concept.estimatedParticipantCount).spoken}${
                concept.hpo ? `, ${describeHpo(concept.hpo).spoken}` : ""
              }`}
              style={{
                ...styles.option,
                ...(index === activeIndex || hoveredKey === index ? styles.optionActive : undefined),
              }}
              // onMouseDown, not onClick: the input's blur would otherwise close the list and
              // unmount this element before a click could land on it.
              onMouseDown={(event) => {
                event.preventDefault();
                applySelection(concept);
              }}
              {...hoverProps(index)}
            >
              <span style={styles.optionName}>
                <span style={styles.optionNameText}>{concept.name}</span>
                {concept.hpo && (
                  <span style={styles.hpo} title={describeHpo(concept.hpo).tooltip} aria-hidden="true">
                    {describeHpo(concept.hpo).label}
                  </span>
                )}
              </span>
              <Estimate
                estimate={concept.estimatedParticipantCount}
                onActiveRow={index === activeIndex || hoveredKey === index}
              />
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p style={styles.error} role="alert">
          Couldn't load matching conditions.
        </p>
      )}
    </div>
  );
}
