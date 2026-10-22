/* Gashtak Skleyka bridge.
 *
 * File protocol, kept compatible with premiere-pro-mcp's CEP connector:
 *   cmd_<id>.jsx   written by Python; claimed here by renaming, then run with
 *                  CSInterface.evalScript
 *   res_<id>.json  the script's return value (it must return a JSON string),
 *                  published by rename so Python never reads half a file
 *   heartbeat.json rewritten every second while the bridge is up
 *
 * The headless extension runs the bridge. The panel only reports on it, so
 * closing the panel never stops the bridge.
 */

// Anything that throws before the guarded start-up below shows in the panel
// instead of leaving it stuck on "Starting…".
window.onerror = function (message, source, line) {
    var el = document.getElementById("status");
    if (el) { el.className = "down"; el.textContent = "Error: " + message + " (line " + line + ")"; }
};

// CEP 12 exposes Node through cep_node rather than as page globals.
function nodeRequire(name) {
    if (typeof require === "function") return require(name);
    if (typeof cep_node !== "undefined" && cep_node.require) return cep_node.require(name);
    throw new Error("Node.js is not enabled in this CEP extension");
}

var cs = new CSInterface();
var fs = nodeRequire("fs");
var path = nodeRequire("path");
var os = nodeRequire("os");
var nodeProcess = typeof process !== "undefined" && process.env ? process : nodeRequire("process");

var LOCAL = nodeProcess.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
var BRIDGE_DIR = path.join(LOCAL, "gashtak-skleyka", "bridge");
var HEARTBEAT = path.join(BRIDGE_DIR, "heartbeat.json");
var LOG = path.join(BRIDGE_DIR, "bridge.log");
var POLL_MS = 150;
var HEARTBEAT_MS = 1000;
var STALE_MS = 3000;

// The bundled CSInterface predates getExtensionID; the native call is older.
var extensionId = typeof cs.getExtensionID === "function"
    ? cs.getExtensionID()
    : window.__adobe_cep__.getExtensionId();
var isHeadless = extensionId.indexOf(".headless") !== -1;

function log(msg) {
    var line = "[" + new Date().toLocaleTimeString() + "] " + msg + "\n";
    try {
        fs.appendFileSync(LOG, line, "utf-8");
        if (fs.statSync(LOG).size > 256 * 1024) {
            var tail = fs.readFileSync(LOG, "utf-8").slice(-64 * 1024);
            fs.writeFileSync(LOG, tail, "utf-8");
        }
    } catch (e) {}
}

function publish(file, content) {
    var staged = file + ".staged";
    fs.writeFileSync(staged, content, "utf-8");
    fs.renameSync(staged, file);
}

// --- headless: the bridge ----------------------------------------------------

var busy = false;
var commands = 0;

function nextCommand() {
    var names;
    try { names = fs.readdirSync(BRIDGE_DIR); } catch (e) { return null; }
    names = names.filter(function (n) { return n.indexOf("cmd_") === 0 && n.slice(-4) === ".jsx"; });
    names.sort();
    return names.length ? names[0] : null;
}

function poll() {
    if (busy) return;
    var name = nextCommand();
    if (!name) return;

    var id = name.slice(4, -4);
    var claimed = path.join(BRIDGE_DIR, name + ".claimed");
    try { fs.renameSync(path.join(BRIDGE_DIR, name), claimed); } catch (e) { return; }
    var script;
    try { script = fs.readFileSync(claimed, "utf-8"); } catch (e) { script = null; }
    try { fs.unlinkSync(claimed); } catch (e) {}
    if (!script) return;

    busy = true;
    var started = Date.now();
    cs.evalScript(script, function (result) {
        var response;
        if (result === undefined || result === null || result === "" || result === "undefined") {
            response = JSON.stringify({ ok: false, error: "evalScript returned nothing" });
        } else if (/^EvalScript error/i.test(result)) {
            response = JSON.stringify({ ok: false, error: "ExtendScript error: " + result });
        } else {
            try { JSON.parse(result); response = result; }
            catch (e) { response = JSON.stringify({ ok: true, data: result }); }
        }
        try { publish(path.join(BRIDGE_DIR, "res_" + id + ".json"), response); }
        catch (e) { log("could not write response " + id + ": " + e.message); }
        commands++;
        log(id + " " + (Date.now() - started) + " ms, " + script.length + " chars");
        busy = false;
        poll();
    });
}

function heartbeat() {
    try {
        publish(HEARTBEAT, JSON.stringify({
            protocol: 1,
            pid: nodeProcess.pid,
            commands: commands,
            busy: busy,
            at: Date.now()
        }));
    } catch (e) {}
}

function startBridge() {
    try { fs.mkdirSync(BRIDGE_DIR, { recursive: true }); } catch (e) {}
    // Commands left from a previous session were never answered; running them
    // now, against whatever project happens to be open, would be wrong.
    try {
        fs.readdirSync(BRIDGE_DIR).forEach(function (n) {
            if (n.indexOf("cmd_") === 0) fs.unlinkSync(path.join(BRIDGE_DIR, n));
        });
    } catch (e) {}
    log("bridge started (pid " + nodeProcess.pid + ")");
    heartbeat();
    setInterval(heartbeat, HEARTBEAT_MS);
    setInterval(poll, POLL_MS);
}

// --- panel: status only ------------------------------------------------------

function refreshPanel() {
    var status = document.getElementById("status");
    var hb = null;
    try { hb = JSON.parse(fs.readFileSync(HEARTBEAT, "utf-8")); } catch (e) {}
    if (hb && Date.now() - hb.at < STALE_MS) {
        status.className = "running";
        status.textContent = "Bridge running — " + hb.commands + " commands" + (hb.busy ? " (busy)" : "");
    } else {
        status.className = "down";
        status.textContent = "Bridge not running";
    }
    var tail = "";
    try { tail = fs.readFileSync(LOG, "utf-8").split("\n").slice(-15).join("\n"); } catch (e) {}
    document.getElementById("log").textContent = tail;
}

try {
    if (isHeadless) {
        startBridge();
    } else {
        document.getElementById("dir").textContent = BRIDGE_DIR;
        refreshPanel();
        setInterval(refreshPanel, 1000);
    }
} catch (e) {
    var msg = (isHeadless ? "headless" : "panel") + " failed to start: " + (e && e.stack || e);
    try { fs.writeFileSync(path.join(os.tmpdir(), "gashtak-skleyka-startup-error.txt"), msg, "utf-8"); } catch (e2) {}
    var el = document.getElementById("status");
    if (el) { el.className = "down"; el.textContent = msg; }
}
