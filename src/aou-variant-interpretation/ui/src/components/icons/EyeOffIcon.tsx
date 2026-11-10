import { baseIconProps, type IconProps } from "./Icon";

export default function EyeOffIcon(props: IconProps) {
  return (
    <svg {...baseIconProps(props)}>
      <path d="M10.7 5.1A10 10 0 0 1 12 5c7 0 10 7 10 7a13 13 0 0 1-1.7 2.7" />
      <path d="M6.6 6.6A13 13 0 0 0 2 12s3 7 10 7a9.7 9.7 0 0 0 5.4-1.6" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="m2 2 20 20" />
    </svg>
  );
}
