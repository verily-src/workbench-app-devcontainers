import { baseIconProps, type IconProps } from "./Icon";

export default function ChevronDownIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
