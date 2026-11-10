import { baseIconProps, type IconProps } from "./Icon";

export default function MenuIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}
