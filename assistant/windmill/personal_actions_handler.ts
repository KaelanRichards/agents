import * as wmill from "npm:windmill-client@1.429.0";

type Headers = Record<string, string | string[] | undefined>;
type Metadata = { headers?: Headers };
type Payload = Record<string, unknown>;
type OAuthResource = { token?: string; access_token?: string };

const ALLOWED: Record<string, string[]> = {
  health_check: [],
  slack_send_message: ["channel", "text", "thread_ts"],
  slack_search_messages: ["query", "max_results"],
  gmail_create_draft: ["account", "to", "subject", "body", "cc", "bcc", "html"],
  gmail_send_email: ["account", "to", "subject", "body", "cc", "bcc", "html"],
  gmail_search_messages: ["account", "query", "max_results"],
  gmail_get_message: ["account", "message_id", "format", "metadata_headers"],
  calendar_create_event: [
    "account",
    "calendar_id",
    "summary",
    "start",
    "end",
    "description",
    "location",
    "attendees",
  ],
  calendar_update_event: [
    "account",
    "calendar_id",
    "event_id",
    "summary",
    "start",
    "end",
    "description",
    "location",
    "attendees",
  ],
  calendar_list_events: ["account", "calendar_id", "time_min", "time_max", "query", "max_results"],
  drive_search_files: ["account", "query", "max_results"],
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

function boundedInt(payload: Payload, key: string, fallback: number, minimum: number, maximum: number): number {
  const raw = payload[key];
  const parsed = typeof raw === "number" ? Math.floor(raw) : Number.parseInt(String(raw ?? fallback), 10);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${key} must be between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function accountValue(payload: Payload): "personal" | "work" {
  const value = optionalString(payload, "account") || "personal";
  if (value !== "personal" && value !== "work") throw new Error("account must be personal or work");
  return value;
}

function accountPath(payload: Payload, personalPath: string, workPath: string): string {
  return accountValue(payload) === "work" ? workPath : personalPath;
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

function verifyBearer(metadata: Metadata | undefined, webhookToken: string) {
  if (!webhookToken) throw new Error("webhook_token variable is required");
  const actual = header(metadata, "authorization").replace(/^Bearer\s+/i, "");
  if (actual !== webhookToken) throw new Error("invalid bearer token");
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

async function slackSearch(slack: OAuthResource, payload: Payload) {
  const params = new URLSearchParams({
    query: requireString(payload, "query"),
    count: String(boundedInt(payload, "max_results", 10, 1, 25)),
    sort: "timestamp",
    sort_dir: "desc",
  });
  const response = await fetch(`https://slack.com/api/search.messages?${params.toString()}`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token(slack)}` },
  });
  const body = await response.json();
  if (!response.ok || body.ok !== true) throw new Error(`Slack search failed: ${JSON.stringify(body)}`);
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

async function gmailSearch(gmail: OAuthResource, payload: Payload) {
  const params = new URLSearchParams({
    q: requireString(payload, "query"),
    maxResults: String(boundedInt(payload, "max_results", 10, 1, 25)),
  });
  const response = await fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages?${params.toString()}`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token(gmail)}` },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`Gmail search failed: ${JSON.stringify(body)}`);
  return body;
}

async function gmailGetMessage(gmail: OAuthResource, payload: Payload) {
  const messageId = encodeURIComponent(requireString(payload, "message_id"));
  const format = optionalString(payload, "format") || "metadata";
  if (!["minimal", "metadata", "full", "raw"].includes(format)) {
    throw new Error("format must be minimal, metadata, full, or raw");
  }
  const params = new URLSearchParams({ format });
  for (const header of optionalString(payload, "metadata_headers").split(",").map((value) => value.trim()).filter(Boolean)) {
    params.append("metadataHeaders", header);
  }
  const response = await fetch(
    `https://gmail.googleapis.com/gmail/v1/users/me/messages/${messageId}?${params.toString()}`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token(gmail)}` },
    },
  );
  const body = await response.json();
  if (!response.ok) throw new Error(`Gmail get message failed: ${JSON.stringify(body)}`);
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

async function calendarList(gcal: OAuthResource, payload: Payload) {
  const calendarId = encodeURIComponent(requireString(payload, "calendar_id"));
  const params = new URLSearchParams({
    timeMin: requireString(payload, "time_min"),
    timeMax: requireString(payload, "time_max"),
    maxResults: String(boundedInt(payload, "max_results", 20, 1, 100)),
    singleEvents: "true",
    orderBy: "startTime",
  });
  const query = optionalString(payload, "query");
  if (query) params.set("q", query);
  const response = await fetch(
    `https://www.googleapis.com/calendar/v3/calendars/${calendarId}/events?${params.toString()}`,
    {
      method: "GET",
      headers: { Authorization: `Bearer ${token(gcal)}` },
    },
  );
  const body = await response.json();
  if (!response.ok) throw new Error(`Calendar list failed: ${JSON.stringify(body)}`);
  return body;
}

async function driveSearch(drive: OAuthResource, payload: Payload) {
  const params = new URLSearchParams({
    q: requireString(payload, "query"),
    pageSize: String(boundedInt(payload, "max_results", 10, 1, 50)),
    fields: "files(id,name,mimeType,webViewLink,modifiedTime,owners(displayName,emailAddress)),nextPageToken",
    orderBy: "recency desc",
    spaces: "drive",
  });
  const response = await fetch(`https://www.googleapis.com/drive/v3/files?${params.toString()}`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token(drive)}` },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(`Drive search failed: ${JSON.stringify(body)}`);
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
  raw_string = "",
  action = "",
  payload: Payload = {},
  slack_resource_path = "u/admin/slack",
  gmail_resource_path = "u/admin/gmail",
  work_gmail_resource_path = "u/admin/work_gmail",
  calendar_resource_path = "u/admin/gcal",
  work_calendar_resource_path = "u/admin/work_gcal",
  drive_resource_path = "u/admin/gdrive",
  work_drive_resource_path = "u/admin/work_gdrive",
  WEBHOOK__METADATA__?: Metadata,
) {
  if (raw_string) {
    const parsed = JSON.parse(raw_string) as { action: string; payload: Payload };
    action = parsed.action;
    payload = parsed.payload ?? {};
  }
  if (WEBHOOK__METADATA__?.headers) {
    const hmac_secret = await wmill.getVariable("u/admin/personal_actions_hmac_secret");
    const webhook_token = await wmill.getVariable("u/admin/personal_actions_webhook_token");
    verifyBearer(WEBHOOK__METADATA__, webhook_token);
    await verifyRequest(action, payload, WEBHOOK__METADATA__, hmac_secret);
  }
  if (action === "health_check") return { ok: true, action, write: false };

  if (action === "slack_send_message") {
    return { ok: true, action, result: await slackSend(await wmill.getResource(slack_resource_path), payload) };
  }
  if (action === "slack_search_messages") {
    return { ok: true, action, result: await slackSearch(await wmill.getResource(slack_resource_path), payload) };
  }
  if (action === "gmail_create_draft") {
    const path = accountPath(payload, gmail_resource_path, work_gmail_resource_path);
    return { ok: true, action, result: await gmailDraft(await wmill.getResource(path), payload) };
  }
  if (action === "gmail_send_email") {
    const path = accountPath(payload, gmail_resource_path, work_gmail_resource_path);
    return { ok: true, action, result: await gmailSend(await wmill.getResource(path), payload) };
  }
  if (action === "gmail_search_messages") {
    const path = accountPath(payload, gmail_resource_path, work_gmail_resource_path);
    return { ok: true, action, result: await gmailSearch(await wmill.getResource(path), payload) };
  }
  if (action === "gmail_get_message") {
    const path = accountPath(payload, gmail_resource_path, work_gmail_resource_path);
    return { ok: true, action, result: await gmailGetMessage(await wmill.getResource(path), payload) };
  }
  if (action === "calendar_create_event") {
    const path = accountPath(payload, calendar_resource_path, work_calendar_resource_path);
    return { ok: true, action, result: await calendarCreate(await wmill.getResource(path), payload) };
  }
  if (action === "calendar_update_event") {
    const path = accountPath(payload, calendar_resource_path, work_calendar_resource_path);
    return { ok: true, action, result: await calendarUpdate(await wmill.getResource(path), payload) };
  }
  if (action === "calendar_list_events") {
    const path = accountPath(payload, calendar_resource_path, work_calendar_resource_path);
    return { ok: true, action, result: await calendarList(await wmill.getResource(path), payload) };
  }
  if (action === "drive_search_files") {
    const path = accountPath(payload, drive_resource_path, work_drive_resource_path);
    return { ok: true, action, result: await driveSearch(await wmill.getResource(path), payload) };
  }
  throw new Error(`unhandled action: ${action}`);
}
