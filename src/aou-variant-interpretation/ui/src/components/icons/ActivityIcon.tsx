import { baseIconProps, type IconProps } from "./Icon";

export default function ActivityIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  );
}
