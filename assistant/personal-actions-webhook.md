# Personal Actions Webhook Backend

The local `personal-actions-mcp` facade sends one normalized JSON request to the configured webhook.
Use this contract for Windmill, Pipedream, Zapier webhooks, Cloudflare Workers, or a private
gateway. The preferred open-source backend is documented in `assistant/windmill/README.md`.

## Environment

Set these locally before enabling live writes:

```bash
personal-actions-configure --url "https://..." --live
```

This writes `~/.config/agents-secrets/personal-actions.env`, which is outside the repo and loaded by
`personal-actions-mcp` and `personal-actions-check`. `PERSONAL_ACTIONS_WEBHOOK_HMAC_SECRET` is
generated automatically; if present, every request includes `X-Personal-Actions-Timestamp` and
`X-Personal-Actions-Signature`.

## Request

Headers:

- `Authorization: Bearer <PERSONAL_ACTIONS_WEBHOOK_TOKEN>` when a token is set.
- `X-Personal-Actions-Idempotency-Key: <uuid>` for all live calls.
- `X-Personal-Actions-Timestamp: <unix-seconds>` when HMAC is enabled.
- `X-Personal-Actions-Signature: v1=<hex-hmac-sha256>` when HMAC is enabled.

Signature payload:

```text
<timestamp>.<raw-request-body>
```

Body:

```json
{
  "action": "slack_send_message",
  "payload": {}
}
```

Allowed actions:

- `health_check`
- `slack_send_message`
- `gmail_create_draft`
- `gmail_send_email`
- `calendar_create_event`
- `calendar_update_event`

The local MCP server exposes only the five mutating actions. `health_check` is reserved for
`personal-actions-check` and must not perform a write.

## Pipedream First Step

Create an HTTP / Webhook-triggered Pipedream workflow. Add the contents of
`assistant/pipedream-personal-actions-validation.js` as the first Node.js code step before any Slack,
Gmail, or Google Calendar action:

```js
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
```

Then branch on `steps.<validation_step_name>.$return_value.action` and call exactly one connected
account action.

## Live Canary Order

1. `personal-actions-check`
2. Gmail draft to self
3. Calendar create on a test calendar
4. Slack message to a private test channel
5. Gmail send to self
6. Calendar update on the test event
