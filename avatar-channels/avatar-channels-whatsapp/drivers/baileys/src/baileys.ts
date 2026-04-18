// src/driver-baileys.ts
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  proto,
} from "@whiskeysockets/baileys";
import WebSocket from "ws";
import pino from "pino";
import fs from "fs";

const logger = pino({ level: "info" });
const CORE_WS_URL = process.env.CORE_WS_URL ?? "ws://127.0.0.1:18789";
const AUTH_DIR = process.env.WHATSAPP_AUTH_DIR ?? "./auth";
const RESET_AUTH = process.env.WHATSAPP_RESET_AUTH === "1";
const WHATSAPP_WHITELIST_ENABLED =
  (process.env.WHATSAPP_WHITELIST_ENABLED ?? "false").toLowerCase() === "true";
const WHATSAPP_WHITELIST_FILE = process.env.WHATSAPP_WHITELIST_FILE ?? "";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

function calcBackoffMs(attempt: number) {
  // 1s, 2s, 4s, 8s, 16s capped at 15s
  return Math.min(1000 * Math.pow(2, Math.min(attempt, 4)), 15000);
}

async function printQr(qr: string) {
  const mod: any = await import("qrcode-terminal");
  const qrcode = mod?.default ?? mod;
  qrcode.generate(qr, { small: true });
}

function nowTs(): number {
  return Math.floor(Date.now() / 1000);
}

function normalizePhone(input: string): string {
  return input.replace(/[^\d]/g, "");
}

function normalizeWhatsAppJid(jid: string): string {
  // 971501234567@s.whatsapp.net -> 971501234567
  const base = (jid ?? "").split("@")[0] ?? "";
  return normalizePhone(base);
}

function isGroupJid(jid: string): boolean {
  return jid.endsWith("@g.us");
}

function loadWhitelistFromFile(): Set<string> {
  if (!WHATSAPP_WHITELIST_FILE) {
    return new Set();
  }

  if (!fs.existsSync(WHATSAPP_WHITELIST_FILE)) {
    logger.warn(
      { file: WHATSAPP_WHITELIST_FILE },
      "Whitelist file not found"
    );
    return new Set();
  }

  const items = fs
    .readFileSync(WHATSAPP_WHITELIST_FILE, "utf-8")
    .split(/\r?\n/)
    .map((line) => normalizePhone(line.trim()))
    .filter(Boolean);

  return new Set(items);
}

function isAllowedWhatsAppUser(jid: string): boolean {
  if (!WHATSAPP_WHITELIST_ENABLED) {
    return true;
  }

  // Groups are not allowed by default
  if (isGroupJid(jid)) {
    return false;
  }

  const whitelist = loadWhitelistFromFile();
  const normalized = normalizeWhatsAppJid(jid);
  return whitelist.has(normalized);
}

function extractText(msg: proto.IWebMessageInfo): string | null {
  const m = msg.message;
  if (!m) return null;

  if (m.conversation) return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;

  return null;
}

function shouldIgnoreMessage(msg: proto.IWebMessageInfo): boolean {
  const remoteJid = msg.key.remoteJid ?? "";

  if (msg.key.fromMe) return true;
  if (!remoteJid) return true;
  if (remoteJid === "status@broadcast") return true;
  if (remoteJid.endsWith("@broadcast")) return true;

  return false;
}

async function main() {
  if (RESET_AUTH && fs.existsSync(AUTH_DIR)) {
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    logger.warn({ AUTH_DIR }, "Auth directory reset before startup");
  }

  // -------- Whitelist Config --------
  logger.info(
    { enabled: WHATSAPP_WHITELIST_ENABLED, file: WHATSAPP_WHITELIST_FILE },
    "whitelist config loaded"
  );

  // -------- Core WS (one connection) --------
  const ws = new WebSocket(CORE_WS_URL);

  ws.on("open", () => logger.info({ CORE_WS_URL }, "Connected to Core WS"));
  ws.on("close", () => logger.warn("Core WS closed"));
  ws.on("error", (err: unknown) => logger.error({ err }, "Core WS error"));

  // Currently available WhatsApp sockets (to be updated upon reconnection)
  let currentSock: ReturnType<typeof makeWASocket> | null = null;
  let lastHealthyAt = 0;

  // Core -> WhatsApp (Register only once to avoid duplicate binding)
  ws.on("message", async (data: WebSocket.RawData) => {
    try {
      const evt = JSON.parse(data.toString("utf-8"));

      if (evt.channel !== "whatsapp") return;
      if (evt.direction !== "out") return;
      if (evt.type !== "text") return;

      if (!currentSock) {
        logger.warn("No active WhatsApp socket; drop outbound");
        return;
      }

      const chat_id: string = evt.chat_id;
      const text: string = evt.text;

      const sent = await currentSock.sendMessage(chat_id, { text });
      lastHealthyAt = Date.now();
      logger.info({ to: chat_id, id: sent?.key?.id }, "sent message");
    } catch (err: unknown) {
      logger.error({ err }, "send outbound error");
    }
  });

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  // -------- WhatsApp socket loop (auto-restart) --------
  let attempt = 0;

  while (true) {
    attempt += 1;
    logger.info({ attempt, AUTH_DIR }, "Starting WhatsApp socket...");

    const sock = makeWASocket({
      version,
      auth: state,
      logger,
    });

    currentSock = sock;

    sock.ev.on("creds.update", saveCreds);

    // WhatsApp -> Core
    sock.ev.on("messages.upsert", async (upsert) => {
      try {
        const msg = upsert.messages?.[0];
        if (!msg) return;
        if (shouldIgnoreMessage(msg)) return;

        const remoteJid = msg.key.remoteJid ?? "";
        if (!isAllowedWhatsAppUser(remoteJid)) {
          logger.warn({ remoteJid }, "Blocked by whitelist");
          return;
        }

        const text = extractText(msg);
        if (!text) return;

        logger.info(
          { from: msg.key.remoteJid, id: msg.key.id, text },
          "inbound message"
        );

        const from = msg.key.remoteJid ?? "unknown";
        const chat_id = msg.key.remoteJid ?? "unknown";
        const message_id = msg.key.id ?? `${chat_id}:${nowTs()}`;

        const inbound = {
          v: 1,
          channel: "whatsapp",
          direction: "in",
          from,
          chat_id,
          message_id,
          ts: nowTs(),
          type: "text",
          text,
          meta: { driver: "baileys" },
        };

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(inbound));
          lastHealthyAt = Date.now();
        } else {
          logger.warn("Core WS not open; drop inbound");
        }
      } catch (err: unknown) {
        logger.error({ err }, "messages.upsert handler error");
      }
    });

    // Wait for this connection to close, then decide whether to exit/reconnect.
    const closeCode: number = await new Promise((resolve) => {
      sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update as any;

        if (qr) {
          logger.info("QR received. Scan in WhatsApp -> Linked devices.");
          await printQr(qr);
        }

        if (connection === "open") {
          logger.info("WhatsApp connection opened");
          attempt = 0;
        }

        if (connection === "close") {
          const reason = (lastDisconnect?.error as any)?.output?.statusCode;
          logger.warn({ reason, lastHealthyAt }, "WhatsApp connection closed");
          resolve(reason ?? 0);
        }
      });
    });

    // loggedOut: Manual clearing of auth and re-pairing are required.
    if (closeCode === DisconnectReason.loggedOut) {
      logger.error({ AUTH_DIR }, "WhatsApp logged out. Delete auth and re-pair.");
      break;
    }

    if (closeCode === DisconnectReason.connectionReplaced) {
      logger.warn("WhatsApp connection replaced by another session.");
    }

    if (closeCode === DisconnectReason.restartRequired) {
      logger.warn("WhatsApp restart required.");
    }

    const backoff = calcBackoffMs(attempt);
    logger.info({ closeCode, backoff }, "Restarting WhatsApp socket...");
    await sleep(backoff);
  }
}

main().catch((e: unknown) => {
  logger.error({ e }, "fatal");
  process.exit(1);
});