import { Box, Chip, IconButton, TextField, Typography } from "@mui/material";
import CancelIcon from "@mui/icons-material/Cancel";
import DeleteIcon from "@mui/icons-material/Delete";
import type { OmopConcept } from "../api";
import {
  DOMAINS_THAT_IGNORE_VALUES,
  DOMAIN_CHOICES,
  MAX_CONCEPT_IDS,
  canHaveValueRange,
  describeValueRange,
  findValueRangeProblem,
  isRuleFullWithOneItem,
} from "../omopRules";
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

// The one line under the rule that says in words what it matches.
function describeRule(rule: RuleDraft): string {
  const valueRange = describeValueRange(rule);
  if (valueRange !== null) {
    return `Matches people who have ${rule.exclude ? "no" : "a"} result ${valueRange}.`;
  }
  return rule.exclude ? "Matches people who have none of these items." : "Matches people who have any of these items.";
}

// What the data holds for the picked measurement, so the user knows the scale (and so the unit).
function describeScale(item: OmopConcept): string {
  if (item.value_min == null || item.value_max == null) {
    return "This item has no numeric results in this data.";
  }
  return `Results in this data run from ${item.value_min} to ${item.value_max}. Leave a box empty for no limit.`;
}

export default function OmopRuleRow({ rule, resourceId, schema, canRemove, onChange, onRemove }: Props) {
  const pickedIds = rule.picked.map((concept) => concept.concept_id);
  const valueRange = describeValueRange(rule);
  const valueRangeProblem = findValueRangeProblem(rule);
  const isFull = rule.picked.length >= MAX_CONCEPT_IDS;
  const holdsNoMoreItems = isRuleFullWithOneItem(rule);
  const domainLabel = (DOMAIN_CHOICES.find((choice) => choice.value === rule.domain)?.label ?? rule.domain).toLowerCase();

  const pickConcept = (concept: OmopConcept) => {
    if (isFull || holdsNoMoreItems || pickedIds.includes(concept.concept_id)) return;
    // A range belongs to one measurement, so a changed item list starts without a range.
    onChange({ ...rule, picked: [...rule.picked, concept], valueMin: "", valueMax: "" });
  };

  const removePickedConcept = (conceptId: number) => {
    onChange({
      ...rule,
      picked: rule.picked.filter((concept) => concept.concept_id !== conceptId),
      valueMin: "",
      valueMax: "",
    });
  };

  // Picked items belong to one domain, so a new domain starts with nothing picked.
  const changeDomain = (domain: string) => {
    onChange({ ...rule, domain, picked: [], valueMin: "", valueMax: "" });
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
        disabled={holdsNoMoreItems}
      />
      {holdsNoMoreItems && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          A {domainLabel} rule holds one item. Remove it to pick another, or add another rule.
        </Typography>
      )}

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
      {canHaveValueRange(rule) && (
        <Box sx={{ display: "flex", gap: 1, mt: 1 }}>
          <TextField
            size="small"
            type="number"
            label="Lowest value"
            placeholder={rule.picked[0].value_min == null ? undefined : String(rule.picked[0].value_min)}
            value={rule.valueMin}
            onChange={(event) => onChange({ ...rule, valueMin: event.target.value })}
            slotProps={{ htmlInput: { step: "any" }, inputLabel: { shrink: true } }}
            error={valueRangeProblem !== null}
          />
          <TextField
            size="small"
            type="number"
            label="Highest value"
            placeholder={rule.picked[0].value_max == null ? undefined : String(rule.picked[0].value_max)}
            value={rule.valueMax}
            onChange={(event) => onChange({ ...rule, valueMax: event.target.value })}
            slotProps={{ htmlInput: { step: "any" }, inputLabel: { shrink: true } }}
            error={valueRangeProblem !== null}
          />
        </Box>
      )}
      {canHaveValueRange(rule) && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
          {describeScale(rule.picked[0])}
        </Typography>
      )}
      {valueRangeProblem !== null && (
        <Typography variant="caption" color="error" sx={{ display: "block" }}>
          {valueRangeProblem}
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        {describeRule(rule)}
      </Typography>
      {DOMAINS_THAT_IGNORE_VALUES.includes(rule.domain) && valueRange === null && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          Any recorded value counts.
        </Typography>
      )}
    </Box>
  );
}
