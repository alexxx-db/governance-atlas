import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SuggestInput } from "../SuggestInput";

const OPTIONS = ["abarreto@shorecp.com", "krzysztof.bialek@shorecp.com"];

describe("SuggestInput (autocomplete combobox)", () => {
  it("shows matching suggestions on focus and filters as you type", () => {
    render(<SuggestInput value="" onChange={() => {}} options={OPTIONS} placeholder="reviewer@x" />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    // Both options visible on empty focus.
    expect(screen.getByRole("listbox")).toBeTruthy();
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("fires onChange with {target:{value}} when an option is chosen", () => {
    const onChange = vi.fn();
    render(<SuggestInput value="abar" onChange={onChange} options={OPTIONS} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    // "abar" matches only abarreto.
    const opts = screen.getAllByRole("option");
    expect(opts).toHaveLength(1);
    fireEvent.mouseDown(opts[0]);
    expect(onChange).toHaveBeenCalledWith({ target: { value: "abarreto@shorecp.com" } });
  });

  it("never blocks a free-text value not in the list", () => {
    const onChange = vi.fn();
    render(<SuggestInput value="" onChange={onChange} options={OPTIONS} />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "brand-new@shorecp.com" } });
    expect(onChange).toHaveBeenCalledWith({ target: { value: "brand-new@shorecp.com" } });
  });

  it("renders a plain combobox with no popup when there are no options", () => {
    render(<SuggestInput value="" onChange={() => {}} options={[]} />);
    fireEvent.focus(screen.getByRole("combobox"));
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("keyboard: ArrowDown highlights and Enter selects", () => {
    const onChange = vi.fn();
    render(<SuggestInput value="" onChange={onChange} options={OPTIONS} />);
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ target: { value: "abarreto@shorecp.com" } });
  });
});
