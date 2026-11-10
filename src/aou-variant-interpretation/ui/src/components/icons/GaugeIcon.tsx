import { baseIconProps, type IconProps } from "./Icon";

export default function GaugeIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M3.34 19a10 10 0 1 1 17.32 0" />
      <path d="m12 14 4-4" />
    </svg>
  );
}
