import { useState } from "react";
import colors from "../../libs/colors";
import * as Style from "../../libs/style";
import Clickable from "../common/Clickable";
import { CheckIcon, CopyIcon } from "../icons";

interface CopyButtonProps {
  getText: () => string;
  label: string;
}

export default function CopyButton({ getText, label }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(getText());
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard access can be denied by the browser; silently ignore.
    }
  }

  return (
    <Clickable
      style={{
        ...Style.buttons.icon,
        borderRadius: 3,
        ...(copied ? { color: colors.textSuccess } : undefined),
      }}
      hoverStyle={Style.buttons.iconHover}
      onClick={handleClick}
      title={label}
      aria-label={label}
    >
      {copied ? <CheckIcon size={12} /> : <CopyIcon size={12} />}
    </Clickable>
  );
}
