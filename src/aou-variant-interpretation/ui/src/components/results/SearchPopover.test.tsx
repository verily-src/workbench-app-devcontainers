import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchPopover, { placePopover } from "./SearchPopover";

function renderPopover(props: Partial<Parameters<typeof SearchPopover>[0]> = {}) {
  const handlers = {
    onVariantsChange: vi.fn(),
    onPhenotypesChange: vi.fn(),
    onCancel: vi.fn(),
    onSearch: vi.fn(),
  };
  render(
    <SearchPopover
      open
      variantsText=""
      phenotypes={[]}
      variantsLimit={50}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

const variantLines = (count: number) => Array.from({ length: count }, (_, index) => `1-${index + 1}-A-G`).join("\n");

describe("SearchPopover", () => {
  afterEach(cleanup);

  it("lays out the entry page's two steps, without their cards", () => {
    renderPopover({ variantsText: "8-11708582-C-T\n8-11708590-G-GAA" });

    expect(screen.getByRole("heading", { name: "Candidate variants" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Phenotype" })).toBeInTheDocument();
    expect(screen.getByText("2 entered")).toBeInTheDocument();
    expect(screen.getByText("limit 50")).toBeInTheDocument();
    expect(screen.getByText("Optional")).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveAttribute("placeholder", "e.g. tetralogy of fallot");
  });

  it("searches and cancels", () => {
    const { onSearch, onCancel } = renderPopover({ variantsText: "8-11708582-C-T" });

    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onSearch).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables search with no variants", () => {
    renderPopover({ variantsText: "\n  \n" });

    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
  });

  it("disables search above the limit, and says how many to remove", () => {
    renderPopover({ variantsText: variantLines(52) });

    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
    expect(screen.getByText("52 entered")).toHaveAttribute("title", "Search is limited to 50 variants.");
    expect(screen.getByText("52 variants entered. Remove 2 to search (limit 50).")).toBeInTheDocument();
  });

  it("restores the variants field's grey border after it loses focus", () => {
    renderPopover();
    const textarea = screen.getByRole("textbox", { name: "Candidate variants" });

    fireEvent.focus(textarea);
    fireEvent.blur(textarea);

    expect(textarea.style.borderColor).toBe("rgb(199, 198, 192)");
  });

  it("searches with Ctrl/⌘+Enter from the variants field, only when a search is allowed", () => {
    const { onSearch } = renderPopover({ variantsText: "8-11708582-C-T" });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Candidate variants" }), { key: "Enter", metaKey: true });
    expect(onSearch).toHaveBeenCalledTimes(1);
    cleanup();

    const empty = renderPopover({ variantsText: "" });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Candidate variants" }), { key: "Enter", ctrlKey: true });
    expect(empty.onSearch).not.toHaveBeenCalled();
  });

  it("searches with Ctrl/⌘+Enter from the phenotype field too", () => {
    const { onSearch } = renderPopover({ variantsText: "8-11708582-C-T" });

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter", metaKey: true });

    expect(onSearch).toHaveBeenCalledTimes(1);
  });

  it("is hidden while closed", () => {
    renderPopover({ open: false });

    expect(screen.queryByRole("dialog", { name: "Edit search" })).not.toBeInTheDocument();
  });

  it("puts focus in the variants field when it opens", () => {
    renderPopover();

    expect(screen.getByRole("textbox", { name: "Candidate variants" })).toHaveFocus();
  });

  it("is marked modal", () => {
    renderPopover();

    expect(screen.getByRole("dialog", { name: "Edit search" })).toHaveAttribute("aria-modal", "true");
  });

  it("keeps Tab inside the popover, wrapping at either end", () => {
    renderPopover({ variantsText: "8-11708582-C-T" });
    const dialog = screen.getByRole("dialog", { name: "Edit search" });
    const first = dialog.querySelector<HTMLElement>("button, textarea, input")!;
    const search = screen.getByRole("button", { name: "Search" });

    search.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(search).toHaveFocus();
  });

  it("skips a disabled Search button when wrapping", () => {
    renderPopover({ variantsText: "" });

    screen.getByRole("button", { name: "Cancel" }).focus();
    fireEvent.keyDown(document, { key: "Tab" });

    expect(screen.getByRole("dialog", { name: "Edit search" })).toContainElement(document.activeElement as HTMLElement);
    expect(screen.getByRole("button", { name: "Cancel" })).not.toHaveFocus();
  });

  it("pulls a Tab from outside back into the popover", () => {
    renderPopover();
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();

    fireEvent.keyDown(document, { key: "Tab" });

    expect(screen.getByRole("dialog", { name: "Edit search" })).toContainElement(document.activeElement as HTMLElement);
    outside.remove();
  });

  it("cancels on Escape and on a click on the backdrop", () => {
    const { onCancel } = renderPopover();

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByTestId("searchPopoverBackdrop"));
    fireEvent.click(screen.getByRole("dialog", { name: "Edit search" }));

    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("leaves an Escape that something inside already handled, e.g. closing the condition dropdown", () => {
    const { onCancel } = renderPopover();

    const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    event.preventDefault();
    document.dispatchEvent(event);

    expect(onCancel).not.toHaveBeenCalled();
  });

  /**
   * Regression guard. When the page could scroll behind the popover (e.g. macOS rubber-banding
   * past the top), the sticky top bar moved while the window-fixed backdrop didn't, leaving an
   * undimmed band above the bar.
   */
  it("locks page scrolling while open, and restores it on close", () => {
    const root = document.documentElement;
    root.style.overflow = "auto";
    const popover = (open: boolean) => (
      <SearchPopover
        open={open}
        variantsText=""
        phenotypes={[]}
        variantsLimit={50}
        onVariantsChange={vi.fn()}
        onPhenotypesChange={vi.fn()}
        onCancel={vi.fn()}
        onSearch={vi.fn()}
      />
    );

    const { rerender } = render(popover(true));
    expect(root.style.overflow).toBe("hidden");

    rerender(popover(false));
    expect(root.style.overflow).toBe("auto");
    root.style.overflow = "";
  });

  it("pads for a space-taking scrollbar while locked, so the page doesn't shift", () => {
    const root = document.documentElement;
    Object.defineProperty(root, "clientWidth", { configurable: true, value: window.innerWidth - 15 });

    renderPopover();
    expect(root.style.paddingRight).toBe("15px");

    cleanup();
    expect(root.style.paddingRight).toBe("");
    // Back to jsdom's own (prototype) getter.
    delete (root as { clientWidth?: number }).clientWidth;
  });

  it("stops listening for Escape once closed", () => {
    const { onCancel } = renderPopover({ open: false });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onCancel).not.toHaveBeenCalled();
  });
});

describe("placePopover", () => {
  it("hangs from the search box at full width when there's room", () => {
    expect(placePopover(110, 1440)).toEqual({ width: 760, left: 0 });
  });

  it("slides left just enough to keep the right margin", () => {
    // 110 + 760 + 20 = 890, so 40px short at 850.
    expect(placePopover(110, 850)).toEqual({ width: 760, left: -40 });
  });

  it("narrows to the viewport less both margins on a small screen", () => {
    const { width, left } = placePopover(110, 390);
    expect(width).toBe(350);
    // Its left edge lands 20px into the viewport.
    expect(110 + left).toBe(20);
  });
});
