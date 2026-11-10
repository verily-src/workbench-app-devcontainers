import { baseIconProps, type IconProps } from "./Icon";

export default function CloseIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}
