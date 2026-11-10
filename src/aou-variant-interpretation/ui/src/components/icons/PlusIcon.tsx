import { baseIconProps, type IconProps } from "./Icon";

export default function PlusIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}
