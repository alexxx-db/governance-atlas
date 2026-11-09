import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  MAX_AVATAR_IMAGE_BYTES,
  UserChip,
  readAvatarFileDataUrl,
} from "./UserChip";

const PNG_BYTES = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00];

function fileFromBytes(bytes, name, type) {
  return new File([new Uint8Array(bytes)], name, { type });
}

describe("readAvatarFileDataUrl", () => {
  it("accepts supported image payloads and normalizes the data URL MIME type", async () => {
    const result = await readAvatarFileDataUrl(
      fileFromBytes(PNG_BYTES, "avatar.png", "image/png"),
    );

    expect(result.accepted).toBe(true);
    expect(result.dataUrl).toMatch(/^data:image\/png;base64,/);
  });

  it("rejects SVG files before they can become avatar data", async () => {
    const result = await readAvatarFileDataUrl(
      new File(["<svg><script>alert(1)</script></svg>"], "avatar.svg", {
        type: "image/svg+xml",
      }),
    );

    expect(result.accepted).toBe(false);
    expect(result.reason).toMatch(/SVG/);
    expect(result.dataUrl).toBe("");
  });

  it("rejects image-labeled files whose payload is not an image", async () => {
    const result = await readAvatarFileDataUrl(
      new File(["not really an image"], "avatar.png", { type: "image/png" }),
    );

    expect(result.accepted).toBe(false);
    expect(result.dataUrl).toBe("");
  });

  it("rejects oversize image files", async () => {
    const bytes = new Uint8Array(MAX_AVATAR_IMAGE_BYTES + 1);
    bytes.set(PNG_BYTES);

    const result = await readAvatarFileDataUrl(
      new File([bytes], "avatar.png", { type: "image/png" }),
    );

    expect(result.accepted).toBe(false);
    expect(result.reason).toMatch(/too large/);
  });
});

describe("UserChip avatar upload", () => {
  let storage;

  beforeEach(() => {
    vi.restoreAllMocks();
    storage = {
      getItem: vi.fn(() => ""),
      setItem: vi.fn(),
    };
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: storage,
    });
  });

  it("stores accepted avatar uploads under the user-specific localStorage key", async () => {
    const { container } = render(
      <UserChip userEmail="abarreto@shorecp.com" userName="Skyler Kohler" role="Admin" />,
    );
    const input = screen.getByLabelText("Upload profile avatar");

    await act(async () => {
      fireEvent.change(input, {
        target: { files: [fileFromBytes(PNG_BYTES, "avatar.png", "image/png")] },
      });
    });

    await waitFor(() => {
      expect(storage.setItem).toHaveBeenCalledWith(
        "axiom:profile-avatar:abarreto@shorecp.com",
        expect.stringMatching(/^data:image\/png;base64,/),
      );
    });
    expect(container.querySelector(".ax-user-chip-avatar img")).not.toBeNull();
  });

  it("does not write rejected avatar uploads to localStorage", async () => {
    render(<UserChip userEmail="abarreto@shorecp.com" userName="Skyler Kohler" role="Admin" />);
    const input = screen.getByLabelText("Upload profile avatar");

    await act(async () => {
      fireEvent.change(input, {
        target: {
          files: [new File(["not really an image"], "avatar.png", { type: "image/png" })],
        },
      });
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
    });

    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("does not render unsafe avatar values already present in localStorage", () => {
    storage.getItem.mockReturnValue("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=");

    const { container } = render(
      <UserChip userEmail="abarreto@shorecp.com" userName="Skyler Kohler" role="Admin" />,
    );

    expect(container.querySelector(".ax-user-chip-avatar img")).toBeNull();
    expect(screen.getByText("SK")).not.toBeNull();
  });

  it("labels avatar upload as a local browser preference", () => {
    render(<UserChip userEmail="abarreto@shorecp.com" userName="Skyler Kohler" role="Admin" />);

    fireEvent.click(screen.getByRole("button", { name: /Open profile menu/i }));

    expect(screen.getByRole("menuitem", { name: /Upload local avatar/i }).getAttribute("title")).toMatch(
      /Stored only in this browser/i,
    );
  });
});
