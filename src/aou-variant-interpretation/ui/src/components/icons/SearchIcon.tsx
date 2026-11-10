import { baseIconProps, type IconProps } from "./Icon";

export default function SearchIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
