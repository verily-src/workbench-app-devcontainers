import { useEffect, useState } from "react";
import { Box, List, ListItemButton, TextField, Typography } from "@mui/material";
import { searchOmopConcepts } from "../api";
import type { OmopConcept } from "../api";

export const SEARCH_WAIT_MS = 300;
export const MIN_SEARCH_CHARS = 3;

interface Props {
  resourceId: string;
  schema: string;
  domain: string;
  // Results with these IDs are greyed out, so the same item cannot be picked twice.
  pickedIds: number[];
  onPick: (concept: OmopConcept) => void;
  // Turns the search box off, for a rule that cannot hold more items.
  disabled?: boolean;
}

function describePersons(count: number): string {
  return count === 1 ? "1 person" : `${count} people`;
}

// " · values 35.5 to 40.5" for a measurement that has numbers, otherwise nothing.
function describeValues(concept: OmopConcept): string {
  if (concept.value_min == null || concept.value_max == null) return "";
  return ` · values ${concept.value_min} to ${concept.value_max}`;
}

export default function ConceptSearchBox({ resourceId, schema, domain, pickedIds, onPick, disabled = false }: Props) {
  const [text, setText] = useState("");
  const [hasFocus, setHasFocus] = useState(false);
  const [results, setResults] = useState<OmopConcept[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const trimmedText = text.trim();
  const isBlank = trimmedText === "";
  const isTooShort = !isBlank && trimmedText.length < MIN_SEARCH_CHARS;

  useEffect(() => {
    if (!hasFocus || isTooShort) {
      setResults([]);
      setHasSearched(false);
      return;
    }
    // A blank box lists the most common items at once. Typed text waits until the user pauses.
    const waitMs = isBlank ? 0 : SEARCH_WAIT_MS;
    let isOutOfDate = false;

    const timer = setTimeout(async () => {
      try {
        const found = await searchOmopConcepts(resourceId, schema, domain, trimmedText);
        if (isOutOfDate) return;
        setResults(found);
        setErrorMessage(null);
      } catch (error) {
        if (isOutOfDate) return;
        setResults([]);
        setErrorMessage(error instanceof Error ? error.message : "The search failed.");
      }
      setHasSearched(true);
    }, waitMs);

    return () => {
      isOutOfDate = true;
      clearTimeout(timer);
    };
  }, [hasFocus, isBlank, isTooShort, trimmedText, resourceId, schema, domain]);

  return (
    <Box>
      <TextField
        size="small"
        fullWidth
        label="Search by name"
        disabled={disabled}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onFocus={() => setHasFocus(true)}
        onBlur={() => setHasFocus(false)}
      />
      {/* Keep the focus in the text box while the user clicks a result, so the list stays open. */}
      <Box onMouseDown={(event) => event.preventDefault()}>
        {isTooShort && (
          <Typography variant="caption" color="text.secondary">
            Type at least {MIN_SEARCH_CHARS} characters.
          </Typography>
        )}
        {errorMessage && (
          <Typography variant="body2" color="error">
            {errorMessage}
          </Typography>
        )}
        {hasSearched && !errorMessage && results.length === 0 && (
          <Typography variant="caption" color="text.secondary">
            No matches. Try other words.
          </Typography>
        )}
        <List dense disablePadding>
          {results.map((concept) => (
            <ListItemButton
              key={concept.concept_id}
              disabled={pickedIds.includes(concept.concept_id)}
              onClick={() => onPick(concept)}
            >
              <Box>
                <Typography variant="body2">{concept.name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {concept.concept_id} · {describePersons(concept.persons)}
                  {describeValues(concept)}
                  {pickedIds.includes(concept.concept_id) && " · added"}
                </Typography>
              </Box>
            </ListItemButton>
          ))}
        </List>
      </Box>
    </Box>
  );
}
