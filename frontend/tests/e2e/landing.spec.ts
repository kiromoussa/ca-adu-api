import { expect, test } from "@playwright/test";

test.describe("marketing landing page", () => {
  test("renders the hero and headline", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/CA ADU Zoning API/);
    await expect(
      page.getByRole("heading", { name: /ADU zoning rules as clean/i })
    ).toBeVisible();
  });

  test("shows all four pricing tiers with spec prices", async ({ page }) => {
    await page.goto("/#pricing");
    await expect(page.getByRole("heading", { name: "Free", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Starter", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Pro", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Enterprise", exact: true })).toBeVisible();
    await expect(page.getByText("$19").first()).toBeVisible();
    await expect(page.getByText("$49").first()).toBeVisible();
  });

  test("links to the docs and dashboard", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Read the docs" })).toHaveAttribute(
      "href",
      "/docs"
    );
    await expect(
      page.getByRole("link", { name: "Get an API key" })
    ).toHaveAttribute("href", "/dashboard");
  });
});
