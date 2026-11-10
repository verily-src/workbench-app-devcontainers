import { baseIconProps, type IconProps } from "./Icon";

export default function TableIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18" />
      <path d="M9 9v12" />
    </svg>
  );
}
