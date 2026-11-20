import { Box, Tooltip, Typography } from "@mui/material";
import type { CriteriaLine } from "../omopRules";

export const NAMES_SHOWN_PER_RULE = 3;

interface Props {
  criteria: CriteriaLine[];
}

// Shows the rules that built an OMOP cohort. It shows nothing for any other data source.
export default function CohortCriteria({ criteria }: Props) {
  if (criteria.length === 0) return null;

  return (
    <Box sx={{ p: 1.5, borderBottom: 1, borderColor: "divider" }}>
      <Typography variant="overline" color="text.secondary">
        Cohort criteria
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2 }}>
        {criteria.map((line, lineNumber) => {
          const shownNames = line.names.slice(0, NAMES_SHOWN_PER_RULE);
          const hiddenCount = line.names.length - shownNames.length;
          return (
            <Typography component="li" variant="body2" key={lineNumber} sx={{ mb: 0.5 }}>
              <strong>{line.heading}:</strong> {shownNames.join(", ")}
              {hiddenCount > 0 && (
                <>
                  {" "}
                  <Tooltip title={line.names.join(", ")}>
                    <span style={{ textDecoration: "underline dotted", cursor: "help" }}>
                      and {hiddenCount} more
                    </span>
                  </Tooltip>
                </>
              )}
            </Typography>
          );
        })}
      </Box>
    </Box>
  );
}
