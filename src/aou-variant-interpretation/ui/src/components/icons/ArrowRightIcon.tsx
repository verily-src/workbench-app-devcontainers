import { baseIconProps, type IconProps } from "./Icon";

export default function ArrowRightIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}
