import crypto from "node:crypto";

const ALLOWED = {
  health_check: [],
  slack_send_message: ["channel", "text", "thread_ts"],
  gmail_create_draft: ["to", "subject", "body", "cc", "bcc", "html"],
  gmail_send_email: ["to", "subject", "body", "cc", "bcc", "html"],
  calendar_create_event: [
    "calendar_id",
    "summary",
    "start",
    "end",
    "description",
    "location",
    "attendees",
  ],
  calendar_update_event: [
    "calendar_id",
    "event_id",
    "summary",
    "start",
    "end",
    "description",
    "location",
    "attendees",
  ],
};

function reject($, status, message) {
  $.respond({ status, body: { ok: false, error: message } });
  throw new Error(message);
}

function header(event, name) {
  const headers = event.headers || {};
  const target = name.toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === target) return Array.isArray(value) ? value[0] : value;
  }
  return "";
}

function timingSafeEqual(a, b) {
  const left = Buffer.from(a || "");
  const right = Buffer.from(b || "");
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

export default defineComponent({
  async run({ steps, $ }) {
    const event = steps.trigger.event;
    const expectedToken = process.env.PERSONAL_ACTIONS_WEBHOOK_TOKEN;
    if (expectedToken) {
      const actual = header(event, "authorization").replace(/^Bearer\s+/i, "");
      if (!timingSafeEqual(actual, expectedToken)) reject($, 401, "invalid bearer token");
    }

    const hmacSecret = process.env.PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET;
    if (hmacSecret) {
      const timestamp = header(event, "x-personal-actions-timestamp");
      const signature = header(event, "x-personal-actions-signature").replace(/^v1=/, "");
      const skew = Math.abs(Math.floor(Date.now() / 1000) - Number(timestamp || 0));
      if (!timestamp || !signature || skew > 300) reject($, 401, "invalid or expired signature");

      const rawBody =
        typeof event.body === "string" ? event.body : JSON.stringify(event.body ?? {});
      const expected = crypto
        .createHmac("sha256", hmacSecret)
        .update(`${timestamp}.${rawBody}`)
        .digest("hex");
      if (!timingSafeEqual(signature, expected)) reject($, 401, "signature mismatch");
    }

    const { action, payload = {} } =
      typeof event.body === "string" ? JSON.parse(event.body) : event.body;
    if (!Object.hasOwn(ALLOWED, action)) reject($, 400, "unsupported action");

    const keys = Object.keys(payload);
    const allowedKeys = new Set(ALLOWED[action]);
    const unknown = keys.filter((key) => !allowedKeys.has(key));
    if (unknown.length) reject($, 400, `unknown payload keys: ${unknown.join(", ")}`);

    if (action === "health_check") {
      $.respond({ status: 200, body: { ok: true, action, write: false } });
      return { ok: true, action, write: false };
    }

    return {
      ok: true,
      action,
      payload,
      idempotencyKey: header(event, "x-personal-actions-idempotency-key"),
    };
  },
});
