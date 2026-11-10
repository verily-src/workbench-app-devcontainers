import type { ReactNode } from "react";
import * as Style from "../libs/style";

interface FieldHintProps {
  children: ReactNode;
}

export default function FieldHint({ children }: FieldHintProps) {
  return <p style={Style.elements.fieldHint}>{children}</p>;
}
