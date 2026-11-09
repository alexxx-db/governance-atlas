import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Drawer } from "../Drawer";

function renderDrawer(props = {}) {
  return render(
    <Drawer open onClose={() => {}} title="Asset preview" {...props}>
      <button>Alpha</button>
      <button>Beta</button>
    </Drawer>,
  );
}

describe("Drawer", () => {
  it("renders nothing when closed", () => {
    render(
      <Drawer open={false} onClose={() => {}} title="Hidden">
        <p>content</p>
      </Drawer>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders an aria-modal dialog labelled by its title, in a portal", () => {
    renderDrawer();
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(document.getElementById(labelId).textContent).toBe("Asset preview");
    // portal: mounted under document.body, not the test container
    expect(dialog.closest(".ax-sys-drawer-root").parentElement).toBe(document.body);
  });

  it("ESC closes", () => {
    const onClose = vi.fn();
    renderDrawer({ onClose });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("scrim click closes", () => {
    const onClose = vi.fn();
    renderDrawer({ onClose });
    fireEvent.click(document.querySelector(".ax-sys-drawer-scrim"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("traps Tab focus inside the panel (wraps both directions)", () => {
    renderDrawer({ footer: <button>Confirm</button> });
    const confirm = screen.getByText("Confirm");
    const closeButton = screen.getByRole("button", { name: "Close" });
    confirm.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(closeButton);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirm);
  });

  it("moves focus into the panel on open and restores it on close", () => {
    const outside = document.createElement("button");
    outside.textContent = "outside";
    document.body.appendChild(outside);
    outside.focus();
    const { rerender } = render(
      <Drawer open onClose={() => {}} title="T">
        <button>Inner</button>
      </Drawer>,
    );
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
    rerender(
      <Drawer open={false} onClose={() => {}} title="T">
        <button>Inner</button>
      </Drawer>,
    );
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });

  it("renders the footer slot and honors the width prop", () => {
    renderDrawer({ footer: <button>Apply</button>, width: 560 });
    expect(screen.getByText("Apply").closest(".ax-sys-drawer-footer")).not.toBeNull();
    const dialog = screen.getByRole("dialog");
    expect(dialog.style.getPropertyValue("--ax-sys-drawer-width")).toBe("560px");
  });

  it("locks body scroll while open and releases it on close", () => {
    const { rerender } = renderDrawer();
    expect(document.body.style.overflow).toBe("hidden");
    rerender(
      <Drawer open={false} onClose={() => {}} title="Asset preview">
        <p>x</p>
      </Drawer>,
    );
    expect(document.body.style.overflow).toBe("");
  });
});
