import { Box, Chip, IconButton, TextField, Typography } from "@mui/material";
import CancelIcon from "@mui/icons-material/Cancel";
import DeleteIcon from "@mui/icons-material/Delete";
import type { OmopConcept } from "../api";
import { DOMAIN_CHOICES, MAX_CONCEPT_IDS } from "../omopRules";
import type { RuleDraft } from "../omopRules";
import ConceptSearchBox from "./ConceptSearchBox";

interface Props {
  rule: RuleDraft;
  resourceId: string;
  schema: string;
  canRemove: boolean;
  onChange: (rule: RuleDraft) => void;
  onRemove: () => void;
}

export default function OmopRuleRow({ rule, resourceId, schema, canRemove, onChange, onRemove }: Props) {
  const pickedIds = rule.picked.map((concept) => concept.concept_id);
  const isFull = rule.picked.length >= MAX_CONCEPT_IDS;

  const pickConcept = (concept: OmopConcept) => {
    if (isFull || pickedIds.includes(concept.concept_id)) return;
    onChange({ ...rule, picked: [...rule.picked, concept] });
  };

  const removePickedConcept = (conceptId: number) => {
    onChange({ ...rule, picked: rule.picked.filter((concept) => concept.concept_id !== conceptId) });
  };

  // Picked items belong to one domain, so a new domain starts with nothing picked.
  const changeDomain = (domain: string) => {
    onChange({ ...rule, domain, picked: [] });
  };

  return (
    <Box sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5, mb: 1.5 }}>
      <Box sx={{ display: "flex", gap: 1, mb: 1, alignItems: "center" }}>
        <TextField
          select
          size="small"
          label="Rule"
          value={rule.exclude ? "exclude" : "include"}
          onChange={(event) => onChange({ ...rule, exclude: event.target.value === "exclude" })}
          slotProps={{ select: { native: true } }}
        >
          <option value="include">Has</option>
          <option value="exclude">Does not have</option>
        </TextField>
        <TextField
          select
          size="small"
          label="Domain"
          value={rule.domain}
          onChange={(event) => changeDomain(event.target.value)}
          slotProps={{ select: { native: true } }}
        >
          {DOMAIN_CHOICES.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </TextField>
        <Box sx={{ flex: 1 }} />
        <IconButton aria-label="Remove rule" disabled={!canRemove} onClick={onRemove}>
          <DeleteIcon />
        </IconButton>
      </Box>

      <ConceptSearchBox
        resourceId={resourceId}
        schema={schema}
        domain={rule.domain}
        pickedIds={pickedIds}
        onPick={pickConcept}
      />

      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 1 }}>
        {rule.picked.map((concept) => (
          <Chip
            key={concept.concept_id}
            label={concept.name}
            size="small"
            onDelete={() => removePickedConcept(concept.concept_id)}
            deleteIcon={<CancelIcon aria-label={`Remove ${concept.name}`} />}
          />
        ))}
      </Box>
      {isFull && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          A rule can hold up to {MAX_CONCEPT_IDS} items.
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        {rule.exclude ? "Matches people who have none of these items." : "Matches people who have any of these items."}
      </Typography>

    </Box>
  );
}
