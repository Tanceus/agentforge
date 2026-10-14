import { errorMessage, formatTime, statusLabel, sumCounts } from "./format";

describe("format helpers", () => {
  it("labels statuses without underscores", () => {
    expect(statusLabel("dead_letter")).toBe("dead letter");
  });

  it("formats timestamps and empty values", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatTime("not-a-date")).toBe("not-a-date");
    expect(formatTime("2026-10-13T09:00:00Z")).toContain("Oct");
  });

  it("reads structured API errors", () => {
    expect(errorMessage({ error: { message: "Start the agent before running tasks" } })).toBe(
      "Start the agent before running tasks",
    );
    expect(errorMessage(null)).toBe("Something went wrong");
  });

  it("sums dashboard counts", () => {
    expect(sumCounts({ completed: 2, failed: 1 })).toBe(3);
  });
});
