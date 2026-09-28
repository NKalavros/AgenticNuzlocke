"use strict";

// Node's env proxy (NODE_USE_ENV_PROXY) covers fetch, not http2.connect.
// The Cursor bridge uses HTTP/2 to api2.cursor.sh, and a direct connect is
// reset by the firewall. Tunnel that session through the HTTP proxy instead.

const http2 = require("node:http2");
const net = require("node:net");
const tls = require("node:tls");
const { Duplex } = require("node:stream");
const { URL } = require("node:url");

if (http2.connect.__nuzlockeHttp2Proxy) {
  module.exports = {};
} else {
  const originalConnect = http2.connect.bind(http2);

  function proxyURL() {
    const raw =
      process.env.HTTPS_PROXY ||
      process.env.https_proxy ||
      process.env.HTTP_PROXY ||
      process.env.http_proxy ||
      "";
    if (!raw) return null;
    let url;
    try {
      url = new URL(raw);
    } catch {
      return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url;
  }

  function bypassed(hostname) {
    const host = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
    const raw = process.env.NO_PROXY || process.env.no_proxy || "";
    return raw
      .split(",")
      .map((part) => part.trim().toLowerCase())
      .filter(Boolean)
      .some((entry) => {
        if (entry === "*") return true;
        if (entry.startsWith(".")) return host.endsWith(entry);
        return host === entry || host.endsWith(`.${entry}`);
      });
  }

  function tunnel(authority) {
    const target = new URL(authority);
    const proxy = proxyURL();
    const pending = [];
    let real = null;
    const stream = new Duplex({
      read() {},
      write(chunk, enc, cb) {
        if (real) real.write(chunk, enc, cb);
        else {
          pending.push(Buffer.from(chunk));
          cb();
        }
      },
    });
    stream.encrypted = true;
    stream.alpnProtocol = "h2";
    stream.setNoDelay = () => stream;
    stream.setKeepAlive = () => stream;
    stream.setTimeout = () => stream;

    const fail = (err) => {
      if (!stream.destroyed) stream.destroy(err);
    };
    if (!proxy) {
      fail(new Error("HTTP/2 proxy preload has no HTTP proxy"));
      return stream;
    }
    const sock = net.connect(Number(proxy.port || 80), proxy.hostname);
    sock.on("error", fail);
    sock.on("connect", () => {
      const host = target.hostname;
      const port = target.port || 443;
      sock.write(
        `CONNECT ${host}:${port} HTTP/1.1\r\nHost: ${host}:${port}\r\n\r\n`,
      );
    });
    let buf = Buffer.alloc(0);
    sock.on("data", function onData(chunk) {
      buf = Buffer.concat([buf, chunk]);
      const idx = buf.indexOf("\r\n\r\n");
      if (idx < 0) return;
      sock.removeListener("data", onData);
      const status = buf.subarray(0, idx).toString("latin1").split("\r\n")[0] || "";
      const rest = buf.subarray(idx + 4);
      if (!/^HTTP\/1\.[01] 200\b/.test(status)) {
        sock.destroy();
        fail(new Error(`proxy CONNECT failed: ${status}`));
        return;
      }
      const secure = tls.connect({
        socket: sock,
        servername: target.hostname,
        ALPNProtocols: ["h2"],
      });
      if (rest.length) secure.unshift(rest);
      secure.on("error", fail);
      secure.on("secureConnect", () => {
        real = secure;
        for (const chunk of pending) secure.write(chunk);
        pending.length = 0;
        secure.on("data", (data) => {
          if (!stream.push(data)) secure.pause();
        });
        stream._read = () => secure.resume();
        secure.on("end", () => stream.push(null));
        secure.on("close", () => {
          if (!stream.readableEnded) stream.push(null);
        });
        stream.on("close", () => secure.destroy());
        stream.emit("connect");
      });
    });
    return stream;
  }

  function connect(authority, options, listener) {
    if (typeof options === "function") {
      listener = options;
      options = undefined;
    }
    const opts = Object.assign({}, options);
    let hostname = "";
    try {
      hostname = new URL(String(authority)).hostname;
    } catch {
      hostname = "";
    }
    if (!proxyURL() || !hostname || bypassed(hostname) || opts.createConnection) {
      return originalConnect(authority, opts, listener);
    }
    opts.createConnection = () => tunnel(String(authority));
    return originalConnect(authority, opts, listener);
  }
  connect.__nuzlockeHttp2Proxy = true;
  http2.connect = connect;
  module.exports = { connect };
}
