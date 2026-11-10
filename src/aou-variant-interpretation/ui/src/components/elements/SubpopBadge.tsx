import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import type { GnomadSubpopCode, SubpopCode } from "../../types/results";
import { SUBPOP_COLOR } from "../../utils/subpopulations";

interface SubpopBadgeProps {
  subpopulation: SubpopCode | GnomadSubpopCode;
}

export default function SubpopBadge({ subpopulation }: SubpopBadgeProps) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 5,
        width: 52,
        padding: "2px 0",
        background: colors.surface1,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        color: colors.textSecondary,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      <span style={Style.colorDot(SUBPOP_COLOR[subpopulation])} />
      {subpopulation}
    </span>
  );
}
