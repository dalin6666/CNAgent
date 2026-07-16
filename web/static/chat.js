const chatForm = document.querySelector("[data-chat-form]");
const chatInput = document.querySelector("[data-chat-input]");
const chatSubmit = document.querySelector("[data-chat-submit]");
const sendLabel = document.querySelector("[data-send-label]");
const messageList = document.querySelector("[data-message-list]");
const resetButton = document.querySelector("[data-reset-chat]");

function appendMessage(role, text, className) {
  const article = document.createElement("article");
  article.className = `message ${className}`;

  const roleNode = document.createElement("div");
  roleNode.className = "message-role";
  roleNode.textContent = role;

  const contentNode = document.createElement("div");
  contentNode.className = "message-content";
  contentNode.textContent = text;

  article.append(roleNode, contentNode);
  messageList.appendChild(article);
  article.scrollIntoView({ block: "end", behavior: "smooth" });
  return article;
}

function setBusy(isBusy) {
  chatSubmit.disabled = isBusy;
  chatInput.disabled = isBusy;
  sendLabel.textContent = isBusy ? "处理中" : "发送";
}

async function postJson(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "请求失败");
  }
  return payload;
}

chatForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) {
    return;
  }

  appendMessage("你", message, "user-message");
  chatInput.value = "";
  const pending = appendMessage("CNAgent", "正在思考...", "assistant-message pending-message");

  setBusy(true);
  try {
    const payload = await postJson("/api/chat", { message });
    pending.querySelector(".message-content").textContent = payload.answer || "没有返回内容";
    pending.classList.remove("pending-message");
  } catch (error) {
    pending.querySelector(".message-content").textContent = error.message;
    pending.classList.add("error-message");
  } finally {
    setBusy(false);
    chatInput.focus();
  }
});

chatInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    chatForm.requestSubmit();
  }
});

resetButton?.addEventListener("click", async () => {
  resetButton.disabled = true;
  try {
    await postJson("/api/chat/reset");
    messageList.replaceChildren();
    appendMessage("CNAgent", "新会话已开始。", "assistant-message");
    chatInput.focus();
  } catch (error) {
    appendMessage("系统", error.message, "assistant-message error-message");
  } finally {
    resetButton.disabled = false;
  }
});
