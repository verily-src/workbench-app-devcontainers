import { baseIconProps, type IconProps } from "./Icon";

/** The dot is a zero-length stroke: with round caps it draws as a disc the stroke's width. */
export default function InfoIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  );
}
