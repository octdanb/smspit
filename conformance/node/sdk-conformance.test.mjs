// SDK conformance: the real twilio-node client against a live smspit.
// Run with a mock instance on SMSPIT_URL (default http://localhost:8025):
//   npm --prefix conformance/node install && npm --prefix conformance/node test

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { before, test } from "node:test";
import twilio from "twilio";

const BASE = process.env.SMSPIT_URL ?? "http://localhost:8025";
const ACCOUNT_SID = "AC" + "0".repeat(32);
const APP = "+15005550006";

const client = twilio(ACCOUNT_SID, "conformance-token");
for (const domain of [client.api, client.messaging, client.verify, client.lookups]) {
  domain.baseUrl = BASE;
}

const uniqueNumber = () =>
  "+1555" + String(BigInt("0x" + randomUUID().replaceAll("-", ""))).slice(0, 7);

async function waitForStatus(sid, status, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let message;
  while (Date.now() < deadline) {
    message = await client.messages(sid).fetch();
    if (message.status === status) return message;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`${sid} never reached ${status}; last: ${message?.status}`);
}

before(async () => {
  await fetch(`${BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ simulate_delivery: true, status_delay_ms: 0 }),
  });
});

test("send and fetch", async () => {
  const to = uniqueNumber();
  const message = await client.messages.create({
    to,
    from: APP,
    body: "node conformance",
  });
  assert.match(message.sid, /^SM[0-9a-f]{32}$/);
  assert.equal(message.numSegments, "1");

  const fetched = await client.messages(message.sid).fetch();
  assert.equal(fetched.body, "node conformance");
  assert.equal(fetched.to, to);
  assert.ok(fetched.dateCreated instanceof Date && !isNaN(fetched.dateCreated));
});

test("list pagination follows next_page_uri", async () => {
  const to = uniqueNumber();
  const sids = new Set();
  for (let index = 0; index < 5; index++) {
    const message = await client.messages.create({ to, from: APP, body: `msg ${index}` });
    sids.add(message.sid);
  }
  const listed = await client.messages.list({ to, pageSize: 2 });
  assert.deepEqual(new Set(listed.map((message) => message.sid)), sids);
});

test("error envelope surfaces Twilio codes", async () => {
  await assert.rejects(
    client.messages.create({ to: "", from: APP, body: "x" }),
    (error) => {
      assert.equal(error.code, 21604);
      assert.equal(error.status, 400);
      return true;
    },
  );
});

test("verify flow", async () => {
  const service = await client.verify.v2.services.create({ friendlyName: "Node conf" });
  assert.match(service.sid, /^VA/);

  const to = uniqueNumber();
  const verification = await client.verify.v2
    .services(service.sid)
    .verifications.create({ to, channel: "sms" });
  assert.equal(verification.status, "pending");

  const latest = await fetch(`${BASE}/api/numbers/${encodeURIComponent(to)}/latest-code`);
  const { code } = await latest.json();
  const approved = await client.verify.v2
    .services(service.sid)
    .verificationChecks.create({ to, code });
  assert.equal(approved.status, "approved");
  assert.equal(approved.valid, true);
});

test("messaging service pool send", async () => {
  const service = await client.messaging.v1.services.create({
    friendlyName: "Node pool",
  });
  await client.messaging.v1
    .services(service.sid)
    .phoneNumbers.create({ phoneNumberSid: "+15550008800" });

  const to = uniqueNumber();
  const message = await client.messages.create({
    to,
    messagingServiceSid: service.sid,
    body: "via node pool",
  });
  assert.equal(message.status, "accepted");
  const delivered = await waitForStatus(message.sid, "delivered");
  assert.equal(delivered.from, "+15550008800");
});

test("lookup", async () => {
  const result = await client.lookups.v2.phoneNumbers("+14155552671").fetch();
  assert.equal(result.valid, true);
  assert.equal(result.countryCode, "US");
  assert.equal(result.phoneNumber, "+14155552671");
});
