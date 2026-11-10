import { baseIconProps, type IconProps } from "./Icon";

export default function ArrowLeftIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </svg>
  );
}
