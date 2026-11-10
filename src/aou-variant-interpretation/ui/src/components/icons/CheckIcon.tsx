import { baseIconProps, type IconProps } from "./Icon";

export default function CheckIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
