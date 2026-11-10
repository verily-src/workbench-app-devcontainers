import { baseIconProps, type IconProps } from "./Icon";

export default function ChevronRightIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}
