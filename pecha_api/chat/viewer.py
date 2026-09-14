"""HTML viewer for testing the chat system - token-based auth.

Lets a tester paste a bearer token, then browse their own groups, a group's
people, or their existing chats (no manual group_id/user_id entry) and start
chatting in that room (auto-created on first message, exactly like a real
client)."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

chat_viewer_router = APIRouter(
    prefix="/view",
    tags=["Chat Viewer"],
)


@chat_viewer_router.get(
    "/chat",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def view_chat():
    """Live chat test page - accepts a token, then lists groups/people/chats to pick from."""
    return _CHAT_VIEWER_HTML


_CHAT_VIEWER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat Test Viewer</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 680px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 90vh;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 16px 20px;
        }

        .header h1 { font-size: 20px; margin-bottom: 6px; }

        .status { display: flex; align-items: center; gap: 8px; font-size: 13px; flex-wrap: wrap; }

        .status-dot {
            width: 10px; height: 10px; border-radius: 50%;
            background: #10b981; animation: pulse 2s infinite;
        }
        .status-dot.offline { background: #ef4444; animation: none; }

        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

        .online-badge {
            background: rgba(255,255,255,0.2);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 12px;
        }

        .back-btn {
            background: rgba(255,255,255,0.15);
            border: none;
            color: white;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            margin-left: auto;
        }
        .back-btn:hover { background: rgba(255,255,255,0.3); }

        /* --- Token screen --- */
        .token-section {
            padding: 24px 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .token-section input {
            padding: 12px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 14px;
            font-family: monospace;
        }
        .token-section input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        button.primary {
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button.primary:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3); }
        button.primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

        /* --- Lobby (tabs + lists) --- */
        .lobby { display: none; flex: 1; flex-direction: column; overflow: hidden; }
        .lobby.active { display: flex; }

        .tabs { display: flex; border-bottom: 1px solid #e5e7eb; background: #f9fafb; }
        .tab {
            flex: 1;
            padding: 12px;
            text-align: center;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            color: #6b7280;
            border-bottom: 2px solid transparent;
        }
        .tab.active { color: #667eea; border-bottom-color: #667eea; }

        .tab-panel { display: none; flex: 1; overflow-y: auto; padding: 12px; }
        .tab-panel.active { display: block; }

        .group-picker {
            padding: 10px 12px;
            border-bottom: 1px solid #e5e7eb;
            background: #f9fafb;
        }
        .group-picker select {
            width: 100%;
            padding: 8px;
            border-radius: 6px;
            border: 1px solid #d1d5db;
            font-size: 13px;
        }

        .list-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s;
        }
        .list-item:hover { background: #f3f4f6; }

        .avatar {
            width: 40px; height: 40px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex; align-items: center; justify-content: center;
            font-weight: 600;
            font-size: 15px;
            flex-shrink: 0;
        }

        .list-item-body { flex: 1; min-width: 0; }
        .list-item-title { font-weight: 600; color: #1f2937; font-size: 14px; }
        .list-item-sub { font-size: 12px; color: #6b7280; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

        .unread-badge {
            background: #667eea;
            color: white;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 10px;
        }

        .empty-state, .loading { text-align: center; color: #9ca3af; padding: 30px 10px; font-size: 14px; }

        /* --- Chat view --- */
        .chat-view { display: none; flex: 1; flex-direction: column; overflow: hidden; }
        .chat-view.active { display: flex; }

        .messages-section { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; }

        .message {
            margin-bottom: 12px;
            padding: 10px 14px;
            background: #f3f4f6;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            max-width: 80%;
        }
        .message.mine {
            align-self: flex-end;
            background: #ede9fe;
            border-left: none;
            border-right: 4px solid #764ba2;
        }

        .message-sender { font-weight: 600; color: #1f2937; margin-bottom: 4px; font-size: 13px; }
        .message-body { color: #374151; line-height: 1.4; word-break: break-word; }
        .message-body.deleted { color: #9ca3af; font-style: italic; }
        .message-time { font-size: 11px; color: #9ca3af; margin-top: 4px; }

        .message-parent {
            border-left: 3px solid #a5b4fc;
            background: rgba(102, 126, 234, 0.08);
            border-radius: 6px;
            padding: 6px 10px;
            margin-bottom: 6px;
            font-size: 12px;
            cursor: pointer;
        }
        .message-parent:hover { background: rgba(102, 126, 234, 0.15); }
        .message-parent-sender { font-weight: 600; color: #4f46e5; }
        .message-parent-body { color: #6b7280; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 380px; }
        .message-parent-body.deleted { color: #9ca3af; font-style: italic; }

        .message-reactions { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
        .reaction-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 2px 8px;
            font-size: 13px;
            cursor: pointer;
            user-select: none;
        }
        .reaction-chip:hover { border-color: #a5b4fc; }
        .reaction-chip.mine { background: #e0e7ff; border-color: #667eea; }
        .reaction-chip .reaction-count { font-size: 11px; color: #6b7280; font-weight: 600; }

        .message-actions { display: none; gap: 6px; margin-top: 6px; }
        .message:hover .message-actions { display: flex; }
        .action-btn {
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 12px;
            cursor: pointer;
            color: #6b7280;
        }
        .action-btn:hover { border-color: #667eea; color: #4f46e5; }
        .action-btn.danger:hover { border-color: #dc2626; color: #dc2626; }

        .emoji-picker {
            position: absolute;
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.15);
            padding: 6px;
            display: flex;
            gap: 4px;
            z-index: 50;
        }
        .emoji-picker button {
            border: none;
            background: none;
            font-size: 20px;
            cursor: pointer;
            padding: 4px;
            border-radius: 6px;
        }
        .emoji-picker button:hover { background: #f3f4f6; }

        .reply-bar {
            display: none;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: #eef2ff;
            border-top: 1px solid #e5e7eb;
            font-size: 13px;
        }
        .reply-bar.active { display: flex; }
        .reply-bar-text { flex: 1; min-width: 0; color: #4b5563; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .reply-bar-text b { color: #4f46e5; }
        .reply-bar-cancel {
            border: none;
            background: none;
            cursor: pointer;
            color: #6b7280;
            font-size: 16px;
            padding: 0 4px;
        }
        .reply-bar-cancel:hover { color: #dc2626; }

        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.5);
            z-index: 100;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .modal-overlay.active { display: flex; }
        .modal {
            background: white;
            border-radius: 12px;
            padding: 20px;
            width: 100%;
            max-width: 400px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .modal h2 { font-size: 16px; color: #1f2937; }
        .modal .modal-target { font-size: 13px; color: #6b7280; background: #f3f4f6; border-radius: 6px; padding: 8px 10px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .modal select, .modal textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
        }
        .modal textarea { resize: vertical; min-height: 70px; }
        .modal-buttons { display: flex; gap: 10px; justify-content: flex-end; }
        .modal-buttons .secondary {
            padding: 10px 18px;
            background: #f3f4f6;
            color: #374151;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
        }

        .success {
            background: #d1fae5;
            color: #065f46;
            padding: 10px 12px;
            border-radius: 8px;
            margin: 8px 12px;
            border-left: 4px solid #10b981;
            font-size: 13px;
        }

        .typing-indicator {
            padding: 4px 20px;
            font-size: 13px;
            color: #6b7280;
            font-style: italic;
            min-height: 22px;
        }

        .input-section {
            border-top: 1px solid #e5e7eb;
            padding: 16px;
            background: #f9fafb;
            display: flex;
            gap: 10px;
        }

        .input-section textarea {
            flex: 1;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            padding: 12px;
            font-family: inherit;
            font-size: 14px;
            resize: none;
            max-height: 100px;
        }
        .input-section textarea:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .error {
            background: #fee2e2;
            color: #991b1b;
            padding: 10px 12px;
            border-radius: 8px;
            margin: 8px 12px;
            border-left: 4px solid #dc2626;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 id="headerTitle">Chat Test Viewer</h1>
            <div class="status" id="statusRow">
                <div class="status-dot offline" id="statusDot"></div>
                <span id="statusText">Not connected</span>
            </div>
        </div>

        <div class="token-section" id="tokenSection">
            <input type="password" id="tokenInput" placeholder="Enter your bearer token" autocomplete="off" />
            <button class="primary" id="tokenBtn">Continue</button>
        </div>

        <div class="lobby" id="lobby">
            <div class="tabs">
                <div class="tab active" data-tab="groups">My Groups</div>
                <div class="tab" data-tab="people">People</div>
                <div class="tab" data-tab="chats">My Chats</div>
            </div>

            <div class="tab-panel active" id="panel-groups">
                <div id="groupsList" class="loading">Loading...</div>
            </div>

            <div class="tab-panel" id="panel-people">
                <div class="group-picker">
                    <select id="peopleGroupSelect"><option value="">Select a group first...</option></select>
                </div>
                <div id="peopleList" class="empty-state">Pick a group above to see its people.</div>
            </div>

            <div class="tab-panel" id="panel-chats">
                <div id="chatsList" class="loading">Loading...</div>
            </div>
        </div>

        <div class="chat-view" id="chatView">
            <div class="messages-section" id="messagesSection"></div>
            <div class="typing-indicator" id="typingIndicator"></div>
            <div class="reply-bar" id="replyBar">
                <div class="reply-bar-text" id="replyBarText"></div>
                <button class="reply-bar-cancel" id="replyBarCancel" title="Cancel reply">&#10005;</button>
            </div>
            <div class="input-section">
                <textarea id="messageInput" placeholder="Type a message... (max 4000 characters)" maxlength="4000"></textarea>
                <button class="primary" id="sendBtn">Send</button>
            </div>
        </div>
    </div>

    <div class="modal-overlay" id="reportModal">
        <div class="modal">
            <h2>Report message</h2>
            <div class="modal-target" id="reportTarget"></div>
            <select id="reportReason">
                <option value="SPAM">Spam</option>
                <option value="HARASSMENT">Harassment</option>
                <option value="HATE_SPEECH">Hate speech</option>
                <option value="INAPPROPRIATE">Inappropriate</option>
                <option value="OTHER">Other</option>
            </select>
            <textarea id="reportDescription" placeholder="Optional description (max 1000 characters)" maxlength="1000"></textarea>
            <div class="modal-buttons">
                <button class="secondary" id="reportCancelBtn">Cancel</button>
                <button class="primary" id="reportSubmitBtn">Report</button>
            </div>
        </div>
    </div>

    <script>
        const apiBase = window.location.origin + "/api/v1";

        let token = null;
        let myEmail = null;
        let myUserId = null;
        let ws = null;
        let roomId = null;
        let typingTimeout = null;
        let lastTypingSent = false;
        let myGroups = [];

        const tokenSection = document.getElementById("tokenSection");
        const tokenInput = document.getElementById("tokenInput");
        const tokenBtn = document.getElementById("tokenBtn");
        const lobby = document.getElementById("lobby");
        const chatView = document.getElementById("chatView");
        const headerTitle = document.getElementById("headerTitle");
        const statusRow = document.getElementById("statusRow");
        const statusDot = document.getElementById("statusDot");
        const statusText = document.getElementById("statusText");
        const groupsList = document.getElementById("groupsList");
        const peopleGroupSelect = document.getElementById("peopleGroupSelect");
        const peopleList = document.getElementById("peopleList");
        const chatsList = document.getElementById("chatsList");
        const messagesSection = document.getElementById("messagesSection");
        const typingIndicator = document.getElementById("typingIndicator");
        const messageInput = document.getElementById("messageInput");
        const sendBtn = document.getElementById("sendBtn");
        const replyBar = document.getElementById("replyBar");
        const replyBarText = document.getElementById("replyBarText");
        const replyBarCancel = document.getElementById("replyBarCancel");
        const reportModal = document.getElementById("reportModal");
        const reportTarget = document.getElementById("reportTarget");
        const reportReason = document.getElementById("reportReason");
        const reportDescription = document.getElementById("reportDescription");
        const reportCancelBtn = document.getElementById("reportCancelBtn");
        const reportSubmitBtn = document.getElementById("reportSubmitBtn");

        const REACTION_EMOJIS = ["\\ud83d\\udc4d", "\\u2764\\ufe0f", "\\ud83d\\ude02", "\\ud83c\\udf89", "\\ud83d\\ude22", "\\ud83d\\ude4f"];
        let replyTo = null;
        let reportMessage = null;
        let openPicker = null;

        function authHeaders() {
            return { "Authorization": `Bearer ${token}` };
        }

        function decodeJwtEmail(jwt) {
            try {
                const payload = JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
                return payload.email || null;
            } catch (e) {
                return null;
            }
        }

        function initials(text) {
            return (text || "?").trim().slice(0, 1).toUpperCase();
        }

        function groupTitle(group) {
            const meta = group.metadata;
            if (Array.isArray(meta) && meta.length > 0) return meta[0].title;
            if (meta && meta.title) return meta.title;
            return group.slug || group.id;
        }

        function showError(container, message) {
            const div = document.createElement("div");
            div.className = "error";
            div.textContent = message;
            container.parentElement.insertBefore(div, container);
            setTimeout(() => div.remove(), 5000);
        }

        /* ---------- Step 1: token ---------- */

        tokenBtn.addEventListener("click", async () => {
            const value = tokenInput.value.trim();
            if (!value) {
                showError(tokenSection, "Please enter a token");
                return;
            }
            token = value;
            myEmail = decodeJwtEmail(token);
            if (!myEmail) {
                showError(tokenSection, "Could not read this token - is it a valid bearer token?");
                token = null;
                return;
            }

            tokenSection.style.display = "none";
            lobby.classList.add("active");
            headerTitle.textContent = myEmail;
            loadMyGroups();
            loadMyChats();
        });

        tokenInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") tokenBtn.click();
        });

        /* ---------- Tabs ---------- */

        document.querySelectorAll(".tab").forEach((tab) => {
            tab.addEventListener("click", () => {
                document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
                document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
                tab.classList.add("active");
                document.getElementById(`panel-${tab.dataset.tab}`).classList.add("active");
            });
        });

        /* ---------- My Groups ---------- */

        async function loadMyGroups() {
            groupsList.className = "loading";
            groupsList.textContent = "Loading...";
            try {
                const [joined, following] = await Promise.all([
                    fetch(`${apiBase}/users/me/joined/author/groups?limit=100`, { headers: authHeaders() }).then(r => r.json()),
                    fetch(`${apiBase}/users/me/following/author/groups?limit=100`, { headers: authHeaders() }).then(r => r.json()),
                ]);
                const byId = new Map();
                (joined.groups || []).forEach(g => byId.set(g.id, g));
                (following.groups || []).forEach(g => byId.set(g.id, g));
                myGroups = Array.from(byId.values());

                renderGroupsList();
                renderPeopleGroupOptions();
            } catch (err) {
                groupsList.textContent = "Failed to load groups: " + err.message;
            }
        }

        function renderGroupsList() {
            groupsList.className = "";
            groupsList.innerHTML = "";
            if (myGroups.length === 0) {
                groupsList.innerHTML = '<div class="empty-state">You have not joined or followed any groups yet.</div>';
                return;
            }
            myGroups.forEach(group => {
                const title = groupTitle(group);
                const div = document.createElement("div");
                div.className = "list-item";
                div.innerHTML = `
                    <div class="avatar">${initials(title)}</div>
                    <div class="list-item-body">
                        <div class="list-item-title">${escapeHtml(title)}</div>
                        <div class="list-item-sub">Group chat</div>
                    </div>
                `;
                div.addEventListener("click", () => openGroupChat(group.id, title));
                groupsList.appendChild(div);
            });
        }

        function renderPeopleGroupOptions() {
            peopleGroupSelect.innerHTML = '<option value="">Select a group first...</option>';
            myGroups.forEach(group => {
                const opt = document.createElement("option");
                opt.value = group.id;
                opt.textContent = groupTitle(group);
                peopleGroupSelect.appendChild(opt);
            });
        }

        /* ---------- People ---------- */

        peopleGroupSelect.addEventListener("change", () => {
            const groupId = peopleGroupSelect.value;
            if (!groupId) {
                peopleList.className = "empty-state";
                peopleList.textContent = "Pick a group above to see its people.";
                return;
            }
            loadGroupPeople(groupId);
        });

        async function loadGroupPeople(groupId) {
            peopleList.className = "loading";
            peopleList.textContent = "Loading...";
            try {
                const data = await fetch(`${apiBase}/chat/groups/${groupId}/people?limit=100`, { headers: authHeaders() }).then(r => r.json());
                peopleList.className = "";
                peopleList.innerHTML = "";
                if (!data.people || data.people.length === 0) {
                    peopleList.innerHTML = '<div class="empty-state">No other people in this group yet.</div>';
                    return;
                }
                data.people.forEach(person => {
                    const displayName = `${person.firstname} ${person.lastname || ""}`.trim() || person.email;
                    const div = document.createElement("div");
                    div.className = "list-item";
                    div.innerHTML = `
                        <div class="avatar">${initials(displayName)}</div>
                        <div class="list-item-body">
                            <div class="list-item-title">${escapeHtml(displayName)}</div>
                            <div class="list-item-sub">${escapeHtml(person.email)}</div>
                        </div>
                    `;
                    div.addEventListener("click", () => openDirectChat(person.user_id, displayName));
                    peopleList.appendChild(div);
                });
            } catch (err) {
                peopleList.textContent = "Failed to load people: " + err.message;
            }
        }

        /* ---------- My Chats ---------- */

        async function loadMyChats() {
            chatsList.className = "loading";
            chatsList.textContent = "Loading...";
            try {
                const data = await fetch(`${apiBase}/chat/rooms?limit=100`, { headers: authHeaders() }).then(r => r.json());
                chatsList.className = "";
                chatsList.innerHTML = "";
                if (!data.rooms || data.rooms.length === 0) {
                    chatsList.innerHTML = '<div class="empty-state">No chats yet - start one from My Groups or People.</div>';
                    return;
                }
                data.rooms.forEach(room => {
                    const isGroup = room.kind === "GROUP";
                    const title = isGroup ? room.name : (room.other_user_name || room.other_user_email || room.name);
                    const preview = room.last_message ? room.last_message.body : "No messages yet";
                    const div = document.createElement("div");
                    div.className = "list-item";
                    div.innerHTML = `
                        <div class="avatar">${initials(title)}</div>
                        <div class="list-item-body">
                            <div class="list-item-title">${escapeHtml(title)}</div>
                            <div class="list-item-sub">${escapeHtml(preview)}</div>
                        </div>
                        ${room.unread_count > 0 ? `<div class="unread-badge">${room.unread_count}</div>` : ""}
                    `;
                    div.addEventListener("click", () => {
                        if (isGroup) {
                            openGroupChat(room.group_id, title);
                        } else if (room.other_user_id) {
                            openDirectChat(room.other_user_id, title);
                        }
                    });
                    chatsList.appendChild(div);
                });
            } catch (err) {
                chatsList.textContent = "Failed to load chats: " + err.message;
            }
        }

        /* ---------- Opening a chat ---------- */

        function openGroupChat(groupId, title) {
            connect(`group_id=${encodeURIComponent(groupId)}`, title);
        }

        function openDirectChat(userId, title) {
            connect(`receiver_id=${encodeURIComponent(userId)}`, title);
        }

        function connect(queryParam, title) {
            if (ws) {
                ws.onclose = null;
                ws.close();
                ws = null;
            }
            roomId = null;
            lastTypingSent = false;
            cancelReply();
            closeEmojiPicker();
            messagesSection.innerHTML = '<div class="loading">Connecting...</div>';
            typingIndicator.textContent = "";

            lobby.classList.remove("active");
            chatView.classList.add("active");
            headerTitle.textContent = title;
            addBackButton();
            updateStatus(false, "Connecting...");

            const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            const encodedToken = encodeURIComponent(token);
            const wsUrl = `${protocol}//${window.location.host}/api/v1/chat/live?token=${encodedToken}&${queryParam}`;

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                updateStatus(true, "Connected");
            };

            ws.onmessage = (event) => {
                let message;
                try {
                    message = JSON.parse(event.data);
                } catch (e) {
                    return;
                }

                if (message.type === "room_info") {
                    roomId = message.room_id;
                    messagesSection.innerHTML = "";
                    loadHistory();
                } else if (message.type === "message_created") {
                    addMessage(message.message);
                    if (message.message.sender_email !== myEmail) setTyping(false);
                } else if (message.type === "reactions_updated") {
                    applyReactionsUpdate(message.message_id, message.reactions || []);
                } else if (message.type === "message_deleted") {
                    applyMessageDeleted(message.message_id, message.deleted_at);
                } else if (message.type === "typing") {
                    if (message.email !== myEmail) setTyping(message.is_typing, message.email);
                } else if (message.type === "presence") {
                    updatePresence(message.count, message.online);
                } else if (message.type === "error") {
                    showError(messagesSection, message.message);
                }
            };

            ws.onerror = () => {
                updateStatus(false, "Connection error");
            };

            ws.onclose = () => {
                updateStatus(false, "Disconnected");
            };
        }

        function addBackButton() {
            let btn = document.getElementById("backBtn");
            if (!btn) {
                btn = document.createElement("button");
                btn.id = "backBtn";
                btn.className = "back-btn";
                btn.textContent = "\\u2190 Switch chat";
                btn.addEventListener("click", goBackToLobby);
                statusRow.appendChild(btn);
            }
        }

        function goBackToLobby() {
            if (ws) {
                ws.onclose = null;
                ws.close();
                ws = null;
            }
            roomId = null;
            cancelReply();
            closeEmojiPicker();
            chatView.classList.remove("active");
            lobby.classList.add("active");
            updateStatus(false, "Not connected");
            loadMyChats();
        }

        function updateStatus(connected, message) {
            statusDot.classList.toggle("offline", !connected);
            statusText.textContent = message;
        }

        function updatePresence(count, online) {
            let badge = document.getElementById("onlineBadge");
            if (!badge) {
                badge = document.createElement("span");
                badge.id = "onlineBadge";
                badge.className = "online-badge";
                statusRow.insertBefore(badge, statusRow.querySelector(".back-btn"));
            }
            (online || []).forEach(p => {
                if (p.email === myEmail) myUserId = p.user_id;
            });
            const names = (online || []).map(p => p.email === myEmail ? "you" : p.email.split("@")[0]);
            badge.textContent = `${count} online` + (names.length ? ` (${names.join(", ")})` : "");
        }

        /* ---------- Messages ---------- */

        function loadHistory() {
            fetch(`${apiBase}/chat/rooms/${roomId}/messages?limit=50`, { headers: authHeaders() })
                .then(r => r.json())
                .then(data => {
                    messagesSection.innerHTML = "";
                    if (!data.messages || data.messages.length === 0) {
                        messagesSection.innerHTML = '<div class="empty-state">No messages yet. Say hello!</div>';
                    } else {
                        data.messages.slice().reverse().forEach(m => addMessage(m));
                    }
                })
                .catch(err => showError(messagesSection, "Failed to load history: " + err.message));
        }

        function addMessage(message) {
            if (messagesSection.querySelector(".empty-state")) {
                messagesSection.innerHTML = "";
            }

            const div = document.createElement("div");
            const isMine = message.sender_email === myEmail;
            const isDeleted = !!message.deleted_at;
            div.className = "message" + (isMine ? " mine" : "");
            div.dataset.messageId = message.id;

            const date = new Date(message.created_at).toLocaleString();

            let parentHtml = "";
            if (message.parent) {
                const parentDeleted = !!message.parent.deleted_at;
                const parentBody = parentDeleted
                    ? deletedBodyText(message.parent)
                    : escapeHtml(message.parent.body);
                parentHtml = `
                    <div class="message-parent" data-parent-id="${escapeHtml(String(message.parent.id))}" title="Go to original message">
                        <div class="message-parent-sender">${escapeHtml(message.parent.sender_email)}</div>
                        <div class="message-parent-body${parentDeleted ? " deleted" : ""}">${parentBody}</div>
                    </div>
                `;
            }

            div.innerHTML = `
                ${parentHtml}
                <div class="message-sender">${escapeHtml(message.sender_email)}</div>
                <div class="message-body${isDeleted ? " deleted" : ""}">${deletedBodyText(message)}</div>
                <div class="message-time">${date}</div>
                <div class="message-reactions"></div>
                <div class="message-actions"></div>
            `;

            const parentEl = div.querySelector(".message-parent");
            if (parentEl) {
                parentEl.addEventListener("click", () => scrollToMessage(parentEl.dataset.parentId));
            }

            if (isDeleted) {
                renderReactions(div, []);
            } else {
                renderActions(div, message, isMine);
                renderReactions(div, message.reactions || []);
            }

            messagesSection.appendChild(div);
            messagesSection.scrollTop = messagesSection.scrollHeight;
        }

        function deletedBodyText(message) {
            if (!message.deleted_at) return escapeHtml(message.body);
            return "\\ud83d\\udeab This message was deleted";
        }

        function renderActions(div, message, isMine) {
            const actions = div.querySelector(".message-actions");
            actions.innerHTML = `
                <button class="action-btn" data-action="react" title="Add reaction">+ React</button>
                <button class="action-btn" data-action="reply" title="Reply to this message">Reply</button>
                ${isMine ? '<button class="action-btn danger" data-action="delete" title="Delete this message">Delete</button>' : '<button class="action-btn danger" data-action="report" title="Report this message">Report</button>'}
            `;
            actions.querySelector('[data-action="react"]').addEventListener("click", (e) => showEmojiPicker(e.currentTarget, message.id));
            actions.querySelector('[data-action="reply"]').addEventListener("click", () => startReply(message));
            const deleteBtn = actions.querySelector('[data-action="delete"]');
            if (deleteBtn) {
                deleteBtn.addEventListener("click", () => deleteMessage(message.id));
            }
            const reportBtn = actions.querySelector('[data-action="report"]');
            if (reportBtn) {
                reportBtn.addEventListener("click", () => openReportModal(message));
            }
        }

        async function deleteMessage(messageId) {
            if (!roomId) return;
            try {
                const response = await fetch(
                    `${apiBase}/chat/rooms/${roomId}/messages/${messageId}`,
                    { method: "DELETE", headers: authHeaders() }
                );
                if (!response.ok) {
                    showError(messagesSection, "Delete failed: " + await readApiError(response));
                    return;
                }
                // The server also broadcasts message_deleted back to this socket;
                // applying it here too keeps the UI responsive if that race loses.
                applyMessageDeleted(messageId, new Date().toISOString());
            } catch (err) {
                showError(messagesSection, "Delete failed: " + err.message);
            }
        }

        function applyMessageDeleted(messageId, deletedAt) {
            const messageEl = messagesSection.querySelector(`[data-message-id="${messageId}"]`);
            if (!messageEl) return;
            if (messageEl.dataset.deleted === "1") return;
            messageEl.dataset.deleted = "1";
            const bodyEl = messageEl.querySelector(".message-body");
            if (bodyEl) {
                bodyEl.classList.add("deleted");
                bodyEl.textContent = "\\ud83d\\udeab This message was deleted";
            }
            const actionsEl = messageEl.querySelector(".message-actions");
            if (actionsEl) actionsEl.innerHTML = "";
            const reactionsEl = messageEl.querySelector(".message-reactions");
            if (reactionsEl) reactionsEl.innerHTML = "";
        }

        function scrollToMessage(messageId) {
            const el = messagesSection.querySelector(`[data-message-id="${messageId}"]`);
            if (el) {
                el.scrollIntoView({ behavior: "smooth", block: "center" });
                el.style.transition = "background 0.3s";
                const original = el.style.background;
                el.style.background = "#fde68a";
                setTimeout(() => { el.style.background = original; }, 900);
            }
        }

        /* ---------- Reactions ---------- */

        function applyReactionsUpdate(messageId, reactions) {
            // Broadcast payloads carry user_ids instead of a viewer-specific
            // reacted_by_me, so recompute it for this client.
            const messageEl = messagesSection.querySelector(`[data-message-id="${messageId}"]`);
            if (!messageEl) return;
            renderReactions(messageEl, reactions.map(r => ({
                ...r,
                reacted_by_me: myUserId != null && (r.user_ids || []).includes(myUserId),
            })));
        }

        function renderReactions(messageEl, reactions) {
            const row = messageEl.querySelector(".message-reactions");
            if (!row) return;
            row.innerHTML = "";
            const messageId = messageEl.dataset.messageId;
            reactions.forEach(r => {
                const chip = document.createElement("button");
                chip.className = "reaction-chip" + (r.reacted_by_me ? " mine" : "");
                const names = (r.users || [])
                    .map(u => u.name || u.email || u.user_id)
                    .filter(Boolean);
                const action = r.reacted_by_me ? "Click to remove your reaction" : "Click to react too";
                chip.title = names.length ? `${names.join(", ")}\\n${action}` : action;
                const emojiSpan = document.createElement("span");
                emojiSpan.textContent = r.emoji;
                const countSpan = document.createElement("span");
                countSpan.className = "reaction-count";
                countSpan.textContent = r.count;
                chip.appendChild(emojiSpan);
                chip.appendChild(countSpan);
                chip.addEventListener("click", () => toggleReaction(messageId, r.emoji, r.reacted_by_me));
                row.appendChild(chip);
            });
        }

        async function toggleReaction(messageId, emoji, reactedByMe) {
            if (!roomId) return;
            try {
                let response;
                if (reactedByMe) {
                    response = await fetch(
                        `${apiBase}/chat/rooms/${roomId}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`,
                        { method: "DELETE", headers: authHeaders() }
                    );
                } else {
                    response = await fetch(
                        `${apiBase}/chat/rooms/${roomId}/messages/${messageId}/reactions`,
                        {
                            method: "POST",
                            headers: { ...authHeaders(), "Content-Type": "application/json" },
                            body: JSON.stringify({ emoji: emoji }),
                        }
                    );
                }
                if (!response.ok) {
                    showError(messagesSection, "Reaction failed: " + await readApiError(response));
                    return;
                }
                const reactions = await response.json();
                const messageEl = messagesSection.querySelector(`[data-message-id="${messageId}"]`);
                if (messageEl) renderReactions(messageEl, reactions);
            } catch (err) {
                showError(messagesSection, "Reaction failed: " + err.message);
            }
        }

        function showEmojiPicker(anchorBtn, messageId) {
            closeEmojiPicker();
            const picker = document.createElement("div");
            picker.className = "emoji-picker";
            REACTION_EMOJIS.forEach(emoji => {
                const btn = document.createElement("button");
                btn.textContent = emoji;
                btn.addEventListener("click", () => {
                    closeEmojiPicker();
                    toggleReaction(messageId, emoji, false);
                });
                picker.appendChild(btn);
            });
            document.body.appendChild(picker);
            const rect = anchorBtn.getBoundingClientRect();
            const pickerRect = picker.getBoundingClientRect();
            let left = rect.left;
            if (left + pickerRect.width > window.innerWidth - 10) {
                left = window.innerWidth - pickerRect.width - 10;
            }
            let top = rect.top - pickerRect.height - 6;
            if (top < 10) top = rect.bottom + 6;
            picker.style.left = `${left}px`;
            picker.style.top = `${top}px`;
            openPicker = picker;
            setTimeout(() => {
                document.addEventListener("click", closeEmojiPickerOnOutsideClick);
            }, 0);
        }

        function closeEmojiPickerOnOutsideClick(e) {
            if (openPicker && !openPicker.contains(e.target)) closeEmojiPicker();
        }

        function closeEmojiPicker() {
            if (openPicker) {
                openPicker.remove();
                openPicker = null;
                document.removeEventListener("click", closeEmojiPickerOnOutsideClick);
            }
        }

        /* ---------- Reply ---------- */

        function startReply(message) {
            replyTo = message;
            replyBarText.innerHTML = `Replying to <b>${escapeHtml(message.sender_email)}</b>: ${escapeHtml(message.body)}`;
            replyBar.classList.add("active");
            messageInput.focus();
        }

        function cancelReply() {
            replyTo = null;
            replyBar.classList.remove("active");
        }

        replyBarCancel.addEventListener("click", cancelReply);

        /* ---------- Report ---------- */

        function openReportModal(message) {
            reportMessage = message;
            reportTarget.textContent = `${message.sender_email}: ${message.body}`;
            reportReason.value = "SPAM";
            reportDescription.value = "";
            reportModal.classList.add("active");
        }

        function closeReportModal() {
            reportMessage = null;
            reportModal.classList.remove("active");
        }

        reportCancelBtn.addEventListener("click", closeReportModal);
        reportModal.addEventListener("click", (e) => {
            if (e.target === reportModal) closeReportModal();
        });

        reportSubmitBtn.addEventListener("click", async () => {
            if (!reportMessage || !roomId) return;
            const payload = { reason: reportReason.value };
            const description = reportDescription.value.trim();
            if (description) payload.description = description;

            reportSubmitBtn.disabled = true;
            try {
                const response = await fetch(
                    `${apiBase}/chat/rooms/${roomId}/messages/${reportMessage.id}/report`,
                    {
                        method: "POST",
                        headers: { ...authHeaders(), "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    }
                );
                if (response.ok) {
                    closeReportModal();
                    showSuccess(messagesSection, "Message reported. Thank you.");
                } else {
                    closeReportModal();
                    showError(messagesSection, "Report failed: " + await readApiError(response));
                }
            } catch (err) {
                closeReportModal();
                showError(messagesSection, "Report failed: " + err.message);
            } finally {
                reportSubmitBtn.disabled = false;
            }
        });

        async function readApiError(response) {
            try {
                const data = await response.json();
                if (data.detail) {
                    return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
                }
                return `HTTP ${response.status}`;
            } catch (e) {
                return `HTTP ${response.status}`;
            }
        }

        function showSuccess(container, message) {
            const div = document.createElement("div");
            div.className = "success";
            div.textContent = message;
            container.parentElement.insertBefore(div, container);
            setTimeout(() => div.remove(), 5000);
        }

        function setTyping(isTyping, email) {
            typingIndicator.textContent = isTyping ? `${email} is typing...` : "";
        }

        function sendMessage() {
            const body = messageInput.value.trim();
            if (!body) return;

            if (ws && ws.readyState === WebSocket.OPEN) {
                const payload = { type: "message", body: body };
                if (replyTo) payload.parent_message_id = replyTo.id;
                ws.send(JSON.stringify(payload));
                messageInput.value = "";
                cancelReply();
                sendTypingState(false);
            } else {
                showError(messagesSection, "Not connected. Please wait...");
            }
        }

        function sendTypingState(isTyping) {
            if (isTyping === lastTypingSent) return;
            lastTypingSent = isTyping;
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "typing", is_typing: isTyping }));
            }
        }

        function escapeHtml(text) {
            const div = document.createElement("div");
            div.textContent = text == null ? "" : text;
            return div.innerHTML;
        }

        sendBtn.addEventListener("click", sendMessage);

        messageInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        messageInput.addEventListener("input", () => {
            sendTypingState(true);
            clearTimeout(typingTimeout);
            typingTimeout = setTimeout(() => sendTypingState(false), 2000);
        });
    </script>
</body>
</html>
"""
