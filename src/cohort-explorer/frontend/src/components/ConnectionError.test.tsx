import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConnectionError from "./ConnectionError";

describe("ConnectionError", () => {
  it("renders the error message", () => {
    render(
      <ConnectionError
        message="Connection refused by database"
        onRetry={() => {}}
        onDisconnect={() => {}}
      />,
    );

    expect(screen.getByText("Unable to load data")).toBeTruthy();
    expect(screen.getByText("Connection refused by database")).toBeTruthy();
  });

  it("calls onRetry when Retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(
      <ConnectionError
        message="Timed out"
        onRetry={onRetry}
        onDisconnect={() => {}}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("calls onDisconnect when Change datasource is clicked", async () => {
    const onDisconnect = vi.fn();
    render(
      <ConnectionError
        message="Timed out"
        onRetry={() => {}}
        onDisconnect={onDisconnect}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /change datasource/i }));
    expect(onDisconnect).toHaveBeenCalledOnce();
  });
});
