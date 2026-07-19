import http from "node:http";
import { expect, test } from "@playwright/test";

const BASE = process.env.SMSPIT_URL ?? "http://localhost:8025";
const AC = "AC" + "1".repeat(32);

let counter = 0;
const uniqueNumber = () =>
  `+1777${String(Date.now()).slice(-4)}${String(counter++).padStart(3, "0")}`;

async function sendSms(to: string, body: string, extra: Record<string, string> = {}) {
  const params = new URLSearchParams({ To: to, From: "+15005550006", Body: body, ...extra });
  const response = await fetch(`${BASE}/2010-04-01/Accounts/${AC}/Messages.json`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: "Basic " + Buffer.from(`${AC}:token`).toString("base64"),
    },
    body: params,
  });
  expect(response.status).toBe(201);
  return response.json();
}

test.beforeAll(async () => {
  await fetch(`${BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ simulate_delivery: true, status_delay_ms: 50 }),
  });
});

test("sent message appears live in the sidebar without reload", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("live")).toBeVisible();

  const to = uniqueNumber();
  await sendSms(to, "hello dashboard");
  await expect(page.locator("aside").getByText(to)).toBeVisible({ timeout: 5000 });
});

test("OTP code gets a copy chip and latest-code header chip", async ({ page }) => {
  const to = uniqueNumber();
  await sendSms(to, "Your verification code is 314159");

  await page.goto("/");
  await page.locator("aside").getByText(to).click();
  await expect(page.getByText("latest code")).toBeVisible();
  await expect(
    page.locator('[data-testid="message-bubble"] button[title="Copy to clipboard"]'),
  ).toBeVisible();
});

test("reply box delivers an inbound webhook and renders the TwiML auto-reply", async ({
  page,
}) => {
  // In-test webhook receiver answering with TwiML.
  const receiver = http.createServer((request, response) => {
    response.writeHead(200, { "Content-Type": "text/xml" });
    response.end("<Response><Message>E2E auto-reply!</Message></Response>");
  });
  await new Promise<void>((resolve) => receiver.listen(9977, resolve));
  await fetch(`${BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ inbound_webhook_url: "http://localhost:9977/sms" }),
  });

  try {
    const to = uniqueNumber();
    await sendSms(to, "start thread");

    await page.goto("/");
    await page.locator("aside").getByText(to).click();
    await page.getByPlaceholder(`Reply as ${to}…`).fill("hi from e2e");
    await page.getByRole("button", { name: "Send" }).click();

    const bubbles = page.locator('[data-testid="message-bubble"]');
    await expect(bubbles.getByText("hi from e2e")).toBeVisible();
    await expect(bubbles.getByText("E2E auto-reply!")).toBeVisible({ timeout: 5000 });
  } finally {
    receiver.close();
    await fetch(`${BASE}/api/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inbound_webhook_url: null }),
    });
  }
});

test("tags: auto-tag rule chips filter the sidebar", async ({ page }) => {
  await fetch(`${BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      auto_tag_rules: [{ tag: "e2e-otp", body_regex: "code is \\d+" }],
    }),
  });
  const tagged = uniqueNumber();
  const plain = uniqueNumber();
  await sendSms(tagged, "Your code is 271828");
  await sendSms(plain, "no code here");

  await page.goto("/");
  const sidebar = page.locator("aside");
  await expect(sidebar.getByText(tagged)).toBeVisible();
  await sidebar.getByRole("button", { name: "e2e-otp" }).first().click();
  await expect(sidebar.getByText(plain)).toBeHidden();
  await expect(sidebar.getByText(tagged)).toBeVisible();
});

test.describe("mobile (375px)", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("inbox → thread → back works full-width with no sideways scroll", async ({
    page,
  }) => {
    const to = uniqueNumber();
    await sendSms(to, "mobile check");

    await page.goto("/");
    const overflowing = () =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth >
          document.documentElement.clientWidth,
      );
    expect(await overflowing()).toBe(false);

    // Tapping a number replaces the inbox with the full-width thread.
    await page.locator("aside").getByText(to).click();
    await expect(
      page.locator('[data-testid="message-bubble"]').first(),
    ).toBeVisible();
    await expect(page.locator("aside")).toBeHidden();
    expect(await overflowing()).toBe(false);

    // The detail drawer covers the screen as an overlay.
    await page.locator('[data-testid="message-bubble"]').first().click();
    await expect(page.getByTestId("message-detail")).toBeVisible();
    await page.getByTitle("Close").click();

    // Back returns to the inbox list.
    await page.getByTitle("Back to inbox").click();
    await expect(page.locator("aside")).toBeVisible();
  });
});

test("message detail drawer shows the Twilio resource", async ({ page }) => {
  const to = uniqueNumber();
  const sent = await sendSms(to, "inspect me");

  await page.goto("/");
  await page.locator("aside").getByText(to).click();
  await page.locator('[data-testid="message-bubble"]').first().click();
  await expect(page.getByTestId("message-detail")).toBeVisible();
  await expect(page.getByText("Twilio resource")).toBeVisible();
  await expect(page.getByText(sent.sid).first()).toBeVisible();
});
