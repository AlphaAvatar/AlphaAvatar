// src/driver-baileys.ts
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  proto,
} from "@whiskeysockets/baileys";
import WebSocket from "ws";
import pino from "pino";

const logger = pino({ level: "info" });
const CORE_WS_URL = process.env.CORE_WS_URL ?? "ws://127.0.0.1:18789";

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

function extractText(msg: proto.IWebMessageInfo): string | null {
  const m = msg.message;
  if (!m) return null;

  if (m.conversation) return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;

  return null;
}

async function main() {
  // -------- Core WS (one connection) --------
  const ws = new WebSocket(CORE_WS_URL);

  ws.on("open", () => logger.info({ CORE_WS_URL }, "Connected to Core WS"));
  ws.on("close", () => logger.warn("Core WS closed"));
  ws.on("error", (err: unknown) => logger.error({ err }, "Core WS error"));

  // 当前可用的 WhatsApp socket（随着重连更新）
  let currentSock: ReturnType<typeof makeWASocket> | null = null;

  // Core -> WhatsApp（只注册一次，避免重复绑定）
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
      logger.info({ to: chat_id, id: sent?.key?.id }, "sent message");
    } catch (err: unknown) {
      logger.error({ err }, "send outbound error");
    }
  });

  // -------- Baileys auth --------
  const { state, saveCreds } = await useMultiFileAuthState("./auth");
  const { version } = await fetchLatestBaileysVersion();

  // -------- WhatsApp socket loop (auto-restart) --------
  let attempt = 0;

  while (true) {
    attempt += 1;
    logger.info({ attempt }, "Starting WhatsApp socket...");

    const sock = makeWASocket({
      version,
      auth: state,
      logger: logger,
    });

    currentSock = sock;

    sock.ev.on("creds.update", saveCreds);

    // WhatsApp -> Core
    sock.ev.on("messages.upsert", async (upsert) => {
      try {
        const msg = upsert.messages?.[0];
        if (!msg) return;

        // Ignore messages you sent to avoid self-triggered loops.
        if (msg.key.fromMe) return;

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
          from: from,
          chat_id,
          message_id,
          ts: nowTs(),
          type: "text",
          text,
          meta: { driver: "baileys" },
        };

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(inbound));
        } else {
          logger.warn("Core WS not open; drop inbound");
        }
      } catch (err: unknown) {
        logger.error({ err }, "messages.upsert handler error");
      }
    });

    // 等待本次连接结束（close），然后决定是否退出/重连
    const closeCode: number = await new Promise((resolve) => {
      sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update as any;

        if (qr) {
          logger.info("QR received. Scan in WhatsApp -> Linked devices.");
          await printQr(qr);
        }

        if (connection === "open") {
          logger.info("WhatsApp connection opened");
          attempt = 0; // Reset to zero upon success
        }

        if (connection === "close") {
          const reason = (lastDisconnect?.error as any)?.output?.statusCode;
          logger.warn({ reason }, "WhatsApp connection closed");
          resolve(reason ?? 0);
        }
      });
    });

    // loggedOut: Manual clearing of auth and re-pairing are required.
    if (closeCode === DisconnectReason.loggedOut) {
      logger.error("WhatsApp logged out. Delete ./auth and re-pair.");
      break;
    }

    // 515 / Other temporary errors: Reconnect after backtracking
    const backoff = calcBackoffMs(attempt);
    logger.info({ closeCode, backoff }, "Restarting WhatsApp socket...");
    await sleep(backoff);
  }
}

main().catch((e: unknown) => {
  logger.error({ e }, "fatal");
  process.exit(1);
});