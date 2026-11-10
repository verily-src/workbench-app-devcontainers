import { baseIconProps, type IconProps } from "./Icon";

interface SortIconProps extends IconProps {
  /** "none" draws both chevrons, the resting state of a sortable column. */
  direction: "none" | "asc" | "desc";
}

/** Stroked chevrons, like the set's other chevrons, rather than filled triangles. */
export default function SortIcon({ direction, ...props }: SortIconProps) {
  return (
    <svg {...baseIconProps(props)}>
      {direction !== "desc" && <path d="m8 9 4-4 4 4" />}
      {direction !== "asc" && <path d="m8 15 4 4 4-4" />}
    </svg>
  );
}
