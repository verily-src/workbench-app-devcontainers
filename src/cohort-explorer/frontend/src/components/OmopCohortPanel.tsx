import { useState } from "react";
import { Accordion, AccordionDetails, AccordionSummary, Box, Button, TextField, Typography } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { createOmopCohort } from "../api";
import { buildSpec, everyRuleHasPickedItem, makeEmptyRule, summarizeRules } from "../omopRules";
import type { CriteriaLine, RuleDraft } from "../omopRules";
import OmopRuleList from "./OmopRuleList";

const DEFAULT_SCHEMA = "public";

interface Props {
  resourceId: string;
  onOpenInExplorer: (schema: string, criteria: CriteriaLine[]) => void | Promise<void>;
}

function describeMatch(count: number): string {
  return count === 1 ? "1 person matches" : `${count} people match`;
}

export default function OmopCohortPanel({ resourceId, onOpenInExplorer }: Props) {
  const [rules, setRules] = useState<RuleDraft[]>(() => [makeEmptyRule()]);
  const [schema, setSchema] = useState(DEFAULT_SCHEMA);
  const [isFinding, setIsFinding] = useState(false);
  const [matchCount, setMatchCount] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // A count belongs to the rules it was made with. Any edit makes it out of date, so hide it.
  const forgetResult = () => {
    setMatchCount(null);
    setErrorMessage(null);
  };

  const changeRules = (newRules: RuleDraft[]) => {
    setRules(newRules);
    forgetResult();
  };

  const changeSchema = (newSchema: string) => {
    setSchema(newSchema);
    forgetResult();
  };

  const findPeople = async () => {
    setIsFinding(true);
    forgetResult();
    try {
      const result = await createOmopCohort(resourceId, buildSpec(schema, rules));
      setMatchCount(result.count);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not find people.");
    } finally {
      setIsFinding(false);
    }
  };

  const openInExplorer = async () => {
    setErrorMessage(null);
    try {
      await onOpenInExplorer(schema, summarizeRules(rules));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Could not open the explorer.");
    }
  };

  const canFindPeople = everyRuleHasPickedItem(rules) && !isFinding;

  return (
    <Box>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1.5 }}>
        Build a cohort
      </Typography>

      <OmopRuleList rules={rules} resourceId={resourceId} schema={schema} onChange={changeRules} />

      <Accordion disableGutters variant="outlined" sx={{ mt: 1, mb: 2 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="body2">Advanced</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <TextField
            size="small"
            fullWidth
            label="Schema name"
            helperText="Change this only if the OMOP tables are in a schema with another name."
            value={schema}
            onChange={(event) => changeSchema(event.target.value)}
          />
        </AccordionDetails>
      </Accordion>

      <Button variant="contained" fullWidth disabled={!canFindPeople} onClick={findPeople}>
        {isFinding ? "Finding people..." : "Find people"}
      </Button>

      {errorMessage && (
        <Typography variant="body2" color="error" sx={{ mt: 1.5 }}>
          {errorMessage}
        </Typography>
      )}

      {matchCount !== null && (
        <Box sx={{ mt: 1.5 }}>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>
            {describeMatch(matchCount)}
          </Typography>
          {matchCount === 0 && (
            <Typography variant="body2" color="text.secondary">
              Change the rules and try again.
            </Typography>
          )}
          <Button
            variant="outlined"
            fullWidth
            sx={{ mt: 1 }}
            disabled={matchCount === 0}
            onClick={openInExplorer}
          >
            Open in Explorer
          </Button>
        </Box>
      )}
    </Box>
  );
}
