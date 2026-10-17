import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProgressBubble } from "../components/chat/ProgressBubble";

describe("ProgressBubble", () => {
  it("shows rows at click time as uploading, then real stages", () => {
    render(
      <ProgressBubble
        docs={[
          { doc_id: "pending:0", filename: "ride.png", stage: "ingest" },
          { doc_id: "doc_1", filename: "hotel.png", stage: "extract" },
        ]}
      />,
    );
    expect(screen.getByText("Uploading…")).toBeInTheDocument();
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    expect(screen.getByText("0/2")).toBeInTheDocument();
  });
});
