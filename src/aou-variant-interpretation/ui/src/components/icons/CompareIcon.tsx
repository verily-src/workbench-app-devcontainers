import { baseIconProps, type IconProps } from "./Icon";

export default function CompareIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M12 3v18" />
      <path d="M7 9h2M15 9h2M7 15h2M15 15h2" />
    </svg>
  );
}
