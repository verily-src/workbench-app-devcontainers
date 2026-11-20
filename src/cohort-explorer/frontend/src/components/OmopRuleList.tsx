import { Button, Typography } from "@mui/material";
import { MAX_RULES, makeEmptyRule } from "../omopRules";
import type { RuleDraft } from "../omopRules";
import OmopRuleRow from "./OmopRuleRow";

interface Props {
  rules: RuleDraft[];
  resourceId: string;
  schema: string;
  onChange: (rules: RuleDraft[]) => void;
}

export default function OmopRuleList({ rules, resourceId, schema, onChange }: Props) {
  const replaceRule = (changed: RuleDraft) => {
    onChange(rules.map((rule) => (rule.id === changed.id ? changed : rule)));
  };

  const removeRule = (ruleId: string) => {
    onChange(rules.filter((rule) => rule.id !== ruleId));
  };

  return (
    <div>
      {rules.map((rule) => (
        <OmopRuleRow
          key={rule.id}
          rule={rule}
          resourceId={resourceId}
          schema={schema}
          canRemove={rules.length > 1}
          onChange={replaceRule}
          onRemove={() => removeRule(rule.id)}
        />
      ))}
      {rules.length > 1 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
          People must match every rule.
        </Typography>
      )}
      <Button size="small" disabled={rules.length >= MAX_RULES} onClick={() => onChange([...rules, makeEmptyRule()])}>
        Add rule
      </Button>
    </div>
  );
}
