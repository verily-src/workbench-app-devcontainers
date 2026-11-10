import type { UseCase } from "../utils/useCases";
import LinkMenu from "./LinkMenu";

interface ExampleMenuProps {
  examples: UseCase[];
  onPick: (example: UseCase) => void;
}

/** "Try an example", as a menu of the curated demo searches. */
export default function ExampleMenu({ examples, onPick }: ExampleMenuProps) {
  return (
    <LinkMenu
      label="Try an example"
      menuLabel="Example searches"
      items={examples.map((example) => ({
        key: example.key,
        title: example.title,
        description: example.description,
        onPick: () => onPick(example),
      }))}
    />
  );
}
