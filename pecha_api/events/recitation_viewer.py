"""HTML test pages for live recitation sync - token-based auth.

Two pages against the same socket: the **emitter** (what an operator drives the
puja from) and the **viewer** (what an attendee's phone does). They are also the
reference implementation of the client rules in
`documentation/live-recitation-sync-api.md` - following `text_id` across texts,
segment-keyed highlighting, the follow toggle and reconnect.

Segment text comes from `POST /recitations/{text_id}`, whose rows are already
language-aligned: a row is matched by *any* of its per-language segment ids, so
a viewer reading English follows an operator clicking Tibetan.
"""

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

recitation_viewer_router = APIRouter(
    prefix="/view",
    tags=["Live Recitation Viewer"],
)


@recitation_viewer_router.get(
    "/events/{event_id}/recitation",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def view_recitation(event_id: UUID):
    """Follower page: auto-scrolls the liturgy to the operator's position."""
    return _VIEWER_HTML.replace("__EVENT_ID__", str(event_id))


@recitation_viewer_router.get(
    "/events/{event_id}/recitation/emitter",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def view_recitation_emitter(event_id: UUID):
    """Operator page: click a line (or press space) to advance the room."""
    return _EMITTER_HTML.replace("__EVENT_ID__", str(event_id))


_SHARED_CSS = """
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
        padding: 20px;
        color: #1f2937;
    }

    .container {
        max-width: 860px;
        margin: 0 auto;
        background: white;
        border-radius: 12px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        overflow: hidden;
        display: flex;
        flex-direction: column;
        height: 92vh;
    }

    .header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 14px 20px;
    }

    .header h1 { font-size: 19px; margin-bottom: 6px; }

    .status { display: flex; align-items: center; gap: 8px; font-size: 13px; flex-wrap: wrap; }

    .status-dot {
        width: 10px; height: 10px; border-radius: 50%;
        background: #10b981; animation: pulse 2s infinite;
    }
    .status-dot.offline { background: #ef4444; animation: none; }

    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

    .badge {
        background: rgba(255,255,255,0.2);
        padding: 2px 8px; border-radius: 10px; font-size: 12px;
    }
    .badge.warn { background: #f59e0b; }

    .setup {
        padding: 12px 20px;
        border-bottom: 1px solid #e5e7eb;
        display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
        background: #f9fafb;
    }

    .setup input, .setup select {
        padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 6px;
        font-size: 13px; font-family: inherit;
    }
    .setup input.token { flex: 1; min-width: 220px; }
    .setup input.text-id { width: 280px; }

    button {
        padding: 8px 14px; border: none; border-radius: 6px; cursor: pointer;
        font-size: 13px; font-weight: 600; background: #667eea; color: white;
    }
    button:disabled { background: #d1d5db; cursor: not-allowed; }
    button.secondary { background: #e5e7eb; color: #374151; }
    button.danger { background: #ef4444; }

    .segments { flex: 1; overflow-y: auto; padding: 8px 0; }

    .segment {
        padding: 10px 20px; border-left: 4px solid transparent;
        font-size: 15px; line-height: 1.7; white-space: pre-wrap;
    }
    .segment .num { color: #9ca3af; font-size: 11px; margin-right: 8px; }
    .segment.current {
        background: #eef2ff; border-left-color: #667eea; font-weight: 600;
    }
    .segment.dim { opacity: 0.55; }
    .segment .translation { display: block; color: #6b7280; font-size: 13px; }

    .empty { padding: 40px 20px; text-align: center; color: #9ca3af; font-size: 14px; }

    .footer {
        padding: 10px 20px; border-top: 1px solid #e5e7eb; background: #f9fafb;
        display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
        font-size: 13px;
    }

    .notice {
        padding: 8px 20px; font-size: 13px; background: #fef3c7; color: #92400e;
        display: none;
    }
    .notice.show { display: block; }
"""


_VIEWER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Recitation Viewer</title>
<style>
__SHARED_CSS__
    .segment.current { scroll-margin: 40vh; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Recitation Viewer</h1>
        <div class="status">
            <span class="status-dot offline" id="dot"></span>
            <span id="state">Not connected</span>
            <span class="badge" id="textBadge">no text</span>
            <span class="badge" id="roundBadge" style="display:none"></span>
        </div>
    </div>

    <div class="setup">
        <input class="token" id="token" type="password" placeholder="Bearer token">
        <select id="language">
            <option value="bo">bo</option>
            <option value="en" selected>en</option>
            <option value="zh">zh</option>
        </select>
        <button id="connect">Connect</button>
        <button class="secondary" id="resync" disabled>Resync</button>
    </div>

    <div class="notice" id="notice"></div>
    <div class="segments" id="segments">
        <div class="empty">Connect to follow the live recitation.</div>
    </div>

    <div class="footer">
        <label><input type="checkbox" id="follow" checked> Follow the operator</label>
        <span id="log" style="color:#6b7280"></span>
    </div>
</div>

<script>
const EVENT_ID = "__EVENT_ID__";
const API = window.location.origin + "/api/v1";

let ws = null, loadedTextId = null, rowsById = {}, currentRow = -1;
let manualScroll = false, retry = 0, ended = false;

const $ = (id) => document.getElementById(id);

function setStatus(online, text) {
    $("dot").className = "status-dot" + (online ? "" : " offline");
    $("state").textContent = text;
}

function notice(text) {
    $("notice").textContent = text || "";
    $("notice").classList.toggle("show", Boolean(text));
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : text;
    return div.innerHTML;
}

async function loadText(textId) {
    notice("");
    $("segments").innerHTML = '<div class="empty">Loading text…</div>';
    const language = $("language").value;
    try {
        const response = await fetch(`${API}/recitations/${encodeURIComponent(textId)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ language, recitation: [language], translations: [] }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        renderSegments(data.segments || []);
        loadedTextId = textId;
        $("textBadge").textContent = data.title || textId;
    } catch (error) {
        $("segments").innerHTML = '<div class="empty">Could not load this text.</div>';
        notice(`Could not load text ${textId}: ${error.message}`);
        loadedTextId = null;
    }
}

/* A row is matched by ANY of its per-language segment ids, which is what lets
   an English reader follow an operator clicking through Tibetan. */
function renderSegments(rows) {
    rowsById = {};
    const html = rows.map((row, i) => {
        const buckets = [row.recitation, row.translations, row.transliterations, row.adaptations];
        let content = "";
        buckets.forEach((bucket) => {
            Object.values(bucket || {}).forEach((segment) => {
                if (!segment || !segment.id) return;
                rowsById[segment.id] = i;
                if (!content) content = segment.content || "";
            });
        });
        return `<div class="segment" id="row-${i}"><span class="num">${i + 1}</span>${escapeHtml(content)}</div>`;
    }).join("");
    $("segments").innerHTML = html || '<div class="empty">This text has no segments.</div>';
}

function highlight(segmentId) {
    const row = rowsById[segmentId];
    if (row === undefined) {
        notice("Out of sync: that line is not in the text you have loaded.");
        return;
    }
    notice("");
    if (currentRow >= 0) {
        const previous = $(`row-${currentRow}`);
        if (previous) previous.classList.remove("current");
    }
    currentRow = row;
    const node = $(`row-${row}`);
    if (!node) return;
    node.classList.add("current");
    if ($("follow").checked && !manualScroll) {
        node.scrollIntoView({ behavior: "smooth", block: "center" });
    }
}

async function onPosition(frame) {
    if (frame.text_id && frame.text_id !== loadedTextId) {
        await loadText(frame.text_id);
    }
    if (frame.round_number) {
        $("roundBadge").style.display = "";
        $("roundBadge").textContent = `round ${frame.round_number}`;
    } else {
        $("roundBadge").style.display = "none";
    }
    highlight(frame.segment_id);
    $("log").textContent = `last position ${new Date().toLocaleTimeString()}`;
}

function connect() {
    const token = $("token").value.trim();
    if (!token) { notice("Paste a bearer token first."); return; }
    localStorage.setItem("recitation_token", token);
    ended = false;

    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(
        `${scheme}//${window.location.host}/api/v1/events/${EVENT_ID}/recitation/live?token=${encodeURIComponent(token)}`
    );

    ws.onopen = () => { retry = 0; setStatus(true, "Connected"); $("resync").disabled = false; };

    ws.onmessage = (event) => {
        const frame = JSON.parse(event.data);
        if (frame.type === "position") onPosition(frame);
        else if (frame.type === "session_info") setStatus(true, frame.is_operator ? "Connected (operator)" : "Connected");
        else if (frame.type === "session_ended") { ended = true; notice("The operator ended this session."); }
        else if (frame.type === "error") notice(`${frame.code}: ${frame.message}`);
    };

    ws.onclose = () => {
        setStatus(false, ended ? "Session ended" : "Reconnecting…");
        $("resync").disabled = true;
        if (ended) return;
        retry = Math.min(retry + 1, 5);
        setTimeout(connect, 1000 * Math.pow(2, retry - 1));
    };

    ws.onerror = () => setStatus(false, "Connection error");
}

/* Scrolling away means the reader is looking ahead deliberately: stop yanking
   them back, and offer a resync instead. */
$("segments").addEventListener("wheel", () => { manualScroll = true; $("follow").checked = false; });
$("segments").addEventListener("touchmove", () => { manualScroll = true; $("follow").checked = false; });

$("follow").addEventListener("change", (event) => { if (event.target.checked) manualScroll = false; });

$("resync").addEventListener("click", () => {
    manualScroll = false;
    $("follow").checked = true;
    const node = $(`row-${currentRow}`);
    if (node) node.scrollIntoView({ behavior: "smooth", block: "center" });
});

$("connect").addEventListener("click", () => { if (ws) ws.close(); connect(); });

setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
}, 30000);

$("token").value = localStorage.getItem("recitation_token") || "";
</script>
</body>
</html>
"""


_EMITTER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Recitation Emitter</title>
<style>
__SHARED_CSS__
    .segment { cursor: pointer; }
    .segment:hover { background: #f3f4f6; }
    .segment.current { scroll-margin: 40vh; }
    .round { display: flex; align-items: center; gap: 6px; }
    .round input { width: 60px; text-align: center; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Recitation Emitter <span style="font-weight:400;font-size:13px">(operator)</span></h1>
        <div class="status">
            <span class="status-dot offline" id="dot"></span>
            <span id="state">Not connected</span>
            <span class="badge" id="roleBadge">role unknown</span>
        </div>
    </div>

    <div class="setup">
        <input class="token" id="token" type="password" placeholder="Bearer token">
        <select id="language">
            <option value="bo" selected>bo</option>
            <option value="en">en</option>
            <option value="zh">zh</option>
        </select>
        <button id="connect">Connect</button>
    </div>
    <div class="setup">
        <input class="text-id" id="textId" placeholder="text_id of the liturgy to recite">
        <button class="secondary" id="load">Load text</button>
        <span class="round">round
            <button class="secondary" id="roundDown">−</button>
            <input id="round" type="number" min="1" value="1">
            <button class="secondary" id="roundUp">+</button>
        </span>
        <button class="danger" id="end" disabled>End session</button>
    </div>

    <div class="notice" id="notice"></div>
    <div class="segments" id="segments">
        <div class="empty">Load a text, then click a line (or press space / ↓) to advance the room.</div>
    </div>

    <div class="footer">
        <span>space / ↓ next · ↑ previous · click any line to jump</span>
        <span id="log" style="color:#6b7280;margin-left:auto"></span>
    </div>
</div>

<script>
const EVENT_ID = "__EVENT_ID__";
const API = window.location.origin + "/api/v1";

let ws = null, segments = [], currentIndex = -1, isOperator = false, ended = false, retry = 0;

const $ = (id) => document.getElementById(id);

function setStatus(online, text) {
    $("dot").className = "status-dot" + (online ? "" : " offline");
    $("state").textContent = text;
}

function notice(text) {
    $("notice").textContent = text || "";
    $("notice").classList.toggle("show", Boolean(text));
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : text;
    return div.innerHTML;
}

async function loadText() {
    const textId = $("textId").value.trim();
    if (!textId) { notice("Enter a text_id first."); return; }
    const language = $("language").value;
    $("segments").innerHTML = '<div class="empty">Loading text…</div>';
    try {
        const response = await fetch(`${API}/recitations/${encodeURIComponent(textId)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ language, recitation: [language], translations: [] }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        segments = (data.segments || []).map((row) => {
            const bucket = row.recitation || {};
            const segment = bucket[language] || Object.values(bucket)[0] || {};
            return { id: segment.id, content: segment.content || "" };
        }).filter((segment) => segment.id);
        currentIndex = -1;
        render();
        notice("");
    } catch (error) {
        $("segments").innerHTML = '<div class="empty">Could not load this text.</div>';
        notice(`Could not load text: ${error.message}`);
    }
}

function render() {
    $("segments").innerHTML = segments.length
        ? segments.map((segment, i) =>
            `<div class="segment" id="row-${i}" data-i="${i}"><span class="num">${i + 1}</span>${escapeHtml(segment.content)}</div>`
          ).join("")
        : '<div class="empty">This text has no segments.</div>';
}

function send(index) {
    if (index < 0 || index >= segments.length) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) { notice("Not connected."); return; }
    if (!isOperator) { notice("This token cannot drive the recitation - you are connected as a viewer."); return; }

    const previous = $(`row-${currentIndex}`);
    if (previous) previous.classList.remove("current");
    currentIndex = index;
    const node = $(`row-${index}`);
    if (node) {
        node.classList.add("current");
        node.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    ws.send(JSON.stringify({
        type: "set",
        text_id: $("textId").value.trim(),
        segment_id: segments[index].id,
        index: index,
        round_number: Number($("round").value) || 1,
    }));
    $("log").textContent = `sent line ${index + 1} at ${new Date().toLocaleTimeString()}`;
}

function connect() {
    const token = $("token").value.trim();
    if (!token) { notice("Paste a bearer token first."); return; }
    localStorage.setItem("recitation_token", token);
    ended = false;

    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(
        `${scheme}//${window.location.host}/api/v1/events/${EVENT_ID}/recitation/live?token=${encodeURIComponent(token)}`
    );

    ws.onopen = () => { retry = 0; setStatus(true, "Connected"); };

    ws.onmessage = (event) => {
        const frame = JSON.parse(event.data);
        if (frame.type === "session_info") {
            isOperator = Boolean(frame.is_operator);
            $("roleBadge").textContent = isOperator ? "operator" : "viewer (cannot publish)";
            $("roleBadge").className = "badge" + (isOperator ? "" : " warn");
            $("end").disabled = !isOperator;
            if (!isOperator) notice("This token has no CMS edit rights on this event, so it cannot drive the recitation.");
        } else if (frame.type === "position") {
            if (frame.text_id && !$("textId").value.trim()) $("textId").value = frame.text_id;
            $("log").textContent = `live position: line ${frame.index != null ? frame.index + 1 : "?"}`;
        } else if (frame.type === "session_ended") {
            ended = true;
            notice("Session ended.");
        } else if (frame.type === "error") {
            notice(`${frame.code}: ${frame.message}`);
        }
    };

    ws.onclose = () => {
        setStatus(false, ended ? "Session ended" : "Reconnecting…");
        if (ended) return;
        retry = Math.min(retry + 1, 5);
        setTimeout(connect, 1000 * Math.pow(2, retry - 1));
    };

    ws.onerror = () => setStatus(false, "Connection error");
}

$("segments").addEventListener("click", (event) => {
    const row = event.target.closest(".segment");
    if (row) send(Number(row.dataset.i));
});

document.addEventListener("keydown", (event) => {
    if (event.target.tagName === "INPUT") return;
    if (event.code === "Space" || event.code === "ArrowDown") {
        event.preventDefault();
        send(currentIndex + 1);
    } else if (event.code === "ArrowUp") {
        event.preventDefault();
        send(currentIndex - 1);
    }
});

$("roundUp").addEventListener("click", () => { $("round").value = Number($("round").value) + 1; });
$("roundDown").addEventListener("click", () => { $("round").value = Math.max(1, Number($("round").value) - 1); });
$("load").addEventListener("click", loadText);
$("connect").addEventListener("click", () => { if (ws) ws.close(); connect(); });
$("end").addEventListener("click", () => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "end" }));
});

setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
}, 30000);

$("token").value = localStorage.getItem("recitation_token") || "";
</script>
</body>
</html>
"""


_VIEWER_HTML = _VIEWER_HTML.replace("__SHARED_CSS__", _SHARED_CSS)
_EMITTER_HTML = _EMITTER_HTML.replace("__SHARED_CSS__", _SHARED_CSS)
