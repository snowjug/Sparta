import { expect, test } from "./support/test";

test.describe("smoke", () => {
  test("home loads for a fresh owner, shows the development-identity banner and an honest protection status", async ({ page, ownerId }) => {
    await page.goto("/");
    await expect(page.getByTestId("dev-banner")).toContainText("Development identity");
    await expect(page.getByTestId("dev-banner")).toContainText(ownerId);
    await expect(page.getByTestId("protection-card")).toBeVisible();
    await expect(page.getByTestId("protection-card")).toContainText(/simulat/i);
    await expect(page.getByRole("main")).toBeVisible();
  });
});
