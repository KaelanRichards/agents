import * as wmill from "npm:windmill-client@1.429.0";

type Headers = Record<string, string | string[] | undefined>;
type Metadata = { headers?: Headers };
type Payload = Record<string, unknown>;
type OAuthResource = { token?: string; access_token?: string };

const ALLOWED: Record<string, string[]> = {
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

function header(metadata: Metadata | undefined, name: string): string {
  const headers = metadata?.headers ?? {};
  const target = name.toLowerCase();
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === target) return Array.isArray(value) ? value[0] ?? "" : value ?? "";
  }
  return "";
}

function requireString(payload: Payload, key: string): string {
  const value = payload[key];
  if (typeof value !== "string" || !value.trim()) throw new Error(`${key} is required`);
  return value.trim();
}

function optionalString(payload: Payload, key: string): string {
  const value = payload[key];
  return typeof value === "string" ? value.trim() : "";
}

function stringList(payload: Payload, key: string): string[] {
  const value = payload[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function boolValue(payload: Payload, key: string): boolean {
  return payload[key] === true;
}

function base64Url(value: string): string {
  return btoa(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function mimeMessage(to: string, subject: string, body: string, cc: string[], bcc: string[], html: boolean): string {
  const lines = [
    `To: ${to}`,
    ...(cc.length ? [`Cc: ${cc.join(", ")}`] : []),
    ...(bcc.length ? [`Bcc: ${bcc.join(", ")}`] : []),
    `Subject: ${subject}`,
    `Content-Type: ${html ? "text/html" : "text/plain"}; charset="UTF-8"`,
    "",
    body,
  ];
  return lines.join("\r\n");
}

async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifyRequest(action: string, payload: Payload, metadata: Metadata | undefined, hmacSecret: string) {
  if (!Object.hasOwn(ALLOWED, action)) throw new Error(`unsupported action: ${action}`);
  const unknown = Object.keys(payload).filter((key) => !ALLOWED[action].includes(key));
  if (unknown.length) throw new Error(`unknown payload keys: ${unknown.join(", ")}`);
  if (action === "health_check") return;

  const idempotencyKey = header(metadata, "x-personal-actions-idempotency-key");
  if (!idempotencyKey) throw new Error("missing idempotency key");

  if (!hmacSecret) throw new Error("hmac_secret argument is required");
  const timestamp = header(metadata, "x-personal-actions-timestamp");
  const signature = header(metadata, "x-personal-actions-signature").replace(/^v1=/, "");
  const skew = Math.abs(Math.floor(Date.now() / 1000) - Number(timestamp || 0));
  if (!timestamp || !signature || skew > 300) throw new Error("invalid or expired signature");

  const canonicalBody = JSON.stringify({ action, payload });
  const expected = await hmacHex(hmacSecret, `${timestamp}.${canonicalBody}`);
  if (signature !== expected) throw new Error("signature mismatch");
}

function token(resource: OAuthResource): string {
  const value = resource.token ?? resource.access_token;
  if (!value) throw new Error("resource is missing an OAuth token");
  return value;
}

async function slackSend(slack: OAuthResource, payload: Payload) {
  const response = await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token(slack)}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      channel: requireString(payload, "channel"),
      text: requireString(payload, "text"),
      thread_ts: optionalString(payload, "thread_ts") || undefined,
    }),
  });
  const body = await response.json();
  if (!response.ok || body.ok !== true) throw new Error(`Slack send failed: ${JSON.stringify(body)}`);
  return body;
}

async function gmailDraft(gmail: OAuthResource, payload: Payload) {
  const raw = base64Url(
    mimeMessage(
      requireString(payload, "to"),
      requireString(payload, "subject"),
      requireString(payload, "body"),
      stringList(payload, "cc"),
      stringList(payload, "bcc"),
      boolValue(payload, "html"),
    ),
  );
  const response = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/drafts", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token(gmail)}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message: { raw } }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`Gmail draft failed: ${JSON.stringify(body)}`);
  return body;
}

async function gmailSend(gmail: OAuthResource, payload: Payload) {
  const raw = base64Url(
    mimeMessage(
      requireString(payload, "to"),
      requireString(payload, "subject"),
      requireString(payload, "body"),
      stringList(payload, "cc"),
      stringList(payload, "bcc"),
      boolValue(payload, "html"),
    ),
  );
  const response = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token(gmail)}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ raw }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`Gmail send failed: ${JSON.stringify(body)}`);
  return body;
}

async function calendarCreate(gcal: OAuthResource, payload: Payload) {
  const calendarId = encodeURIComponent(requireString(payload, "calendar_id"));
  const response = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${calendarId}/events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token(gcal)}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      summary: requireString(payload, "summary"),
      start: { dateTime: requireString(payload, "start") },
      end: { dateTime: requireString(payload, "end") },
      description: optionalString(payload, "description") || undefined,
      location: optionalString(payload, "location") || undefined,
      attendees: stringList(payload, "attendees").map((email) => ({ email })),
    }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`Calendar create failed: ${JSON.stringify(body)}`);
  return body;
}

async function calendarUpdate(gcal: OAuthResource, payload: Payload) {
  const calendarId = encodeURIComponent(requireString(payload, "calendar_id"));
  const eventId = encodeURIComponent(requireString(payload, "event_id"));
  const update: Record<string, unknown> = {};
  for (const key of ["summary", "description", "location"]) {
    const value = optionalString(payload, key);
    if (value) update[key] = value;
  }
  if (optionalString(payload, "start")) update.start = { dateTime: optionalString(payload, "start") };
  if (optionalString(payload, "end")) update.end = { dateTime: optionalString(payload, "end") };
  if (stringList(payload, "attendees").length) {
    update.attendees = stringList(payload, "attendees").map((email) => ({ email }));
  }
  const response = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${calendarId}/events/${eventId}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token(gcal)}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(update),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`Calendar update failed: ${JSON.stringify(body)}`);
  return body;
}

export async function main(
  action: string,
  payload: Payload = {},
  hmac_secret = "",
  slack_resource_path = "u/admin/slack",
  gmail_resource_path = "u/admin/gmail",
  calendar_resource_path = "u/admin/gcal",
  WEBHOOK__METADATA__?: Metadata,
) {
  await verifyRequest(action, payload, WEBHOOK__METADATA__, hmac_secret);
  if (action === "health_check") return { ok: true, action, write: false };

  if (action === "slack_send_message") {
    return { ok: true, action, result: await slackSend(await wmill.getResource(slack_resource_path), payload) };
  }
  if (action === "gmail_create_draft") {
    return { ok: true, action, result: await gmailDraft(await wmill.getResource(gmail_resource_path), payload) };
  }
  if (action === "gmail_send_email") {
    return { ok: true, action, result: await gmailSend(await wmill.getResource(gmail_resource_path), payload) };
  }
  if (action === "calendar_create_event") {
    return { ok: true, action, result: await calendarCreate(await wmill.getResource(calendar_resource_path), payload) };
  }
  if (action === "calendar_update_event") {
    return { ok: true, action, result: await calendarUpdate(await wmill.getResource(calendar_resource_path), payload) };
  }
  throw new Error(`unhandled action: ${action}`);
}
