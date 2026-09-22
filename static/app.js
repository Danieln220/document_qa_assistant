/*
  Document Desk - the page's behaviour.

  Small on purpose: send a question, show the answer, show the tags. No
  framework and no build step, so the whole front end is three files a client's
  own developer can read.
*/

const thread = document.getElementById("thread");
const form = document.getElementById("composer");
const input = document.getElementById("question");
const send = document.getElementById("send");
const footnote = document.getElementById("footnote");

/* ---------------------------------------------------------------- start-up */

// Show which documents are indexed, so nobody has to guess what it can see.
fetch("/api/status")
  .then((response) => response.json())
  .then((status) => {
    document.getElementById("company").textContent = status.company;
    document.title = `Document Desk - ${status.company}`;

    const list = document.getElementById("documents");
    list.innerHTML = "";
    for (const doc of status.documents) {
      const scanned = /scan/i.test(doc.name);
      // A scan is already known to be a PDF, so the badge says SCAN, not both.
      const where = scanned
        ? `SCAN · ${doc.pages}pp`
        : (doc.pages ? `${doc.type} · ${doc.pages}pp` : doc.type);
      list.insertAdjacentHTML("beforeend", `
        <li>
          <a href="${doc.url}" target="_blank" rel="noopener">
            <span>${escapeHtml(prettyName(doc.name))}</span>
            <span class="kind ${scanned ? "scan" : ""}">${where}</span>
          </a>
        </li>`);
    }
    footnote.textContent = `${status.documents.length} documents · ${status.passages} passages · ${status.model}`;
  })
  .catch(() => {
    footnote.textContent = "Could not reach the assistant. Is the server running?";
  });

// The example questions are there to be clicked during a demo.
document.getElementById("starters").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button) ask(button.dataset.q);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  ask(input.value);
});

/* -------------------------------------------------------------- asking */

async function ask(question) {
  question = (question || "").trim();
  if (!question || send.disabled) return;

  document.querySelector(".opener")?.remove();
  input.value = "";
  addQuestion(question);
  const working = addWorking();
  setBusy(true);

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const result = await response.json();
    working.replaceWith(buildReply(result));
  } catch {
    // The network failed, or the server went away mid-question.
    working.replaceWith(buildReply({
      answered: false,
      text: "Could not reach the assistant. Please try that question again.",
      citations: [],
    }));
  } finally {
    setBusy(false);
    input.focus();
  }
}

function setBusy(busy) {
  send.disabled = busy;
  send.textContent = busy ? "Asking" : "Ask";
}

/* ------------------------------------------------------------- rendering */

function addQuestion(text) {
  const node = document.createElement("div");
  node.className = "ask";
  node.textContent = text;
  thread.append(node);
  scrollDown();
}

function addWorking() {
  const node = document.createElement("div");
  node.className = "working";
  node.innerHTML = `<span class="bars"><i></i><i></i><i></i></span> Reading the documents`;
  thread.append(node);
  scrollDown();
  return node;
}

function buildReply(result) {
  const node = document.createElement("div");
  node.className = result.answered ? "reply" : "reply refused";

  const text = document.createElement("div");
  text.className = "text";
  text.textContent = result.text;
  node.append(text);

  if (result.answered && result.citations.length) {
    // One tag per checked quote: document, where it sits, and the line itself.
    const tags = document.createElement("div");
    tags.className = "tags";
    for (const c of result.citations) {
      const tag = document.createElement("article");
      tag.className = "tag";
      tag.innerHTML = `
        <div class="tag-head">
          <span class="file">${escapeHtml(prettyName(c.file))}</span>
          <span>${escapeHtml(c.location)}</span>
          ${c.ocr ? '<span class="flag">read by OCR</span>' : ""}
          ${c.exact ? "" : '<span class="flag">close match</span>'}
          <a href="${c.url}" target="_blank" rel="noopener">Open</a>
        </div>
        <blockquote>${escapeHtml(c.quote)}</blockquote>`;
      tags.append(tag);
    }
    node.append(tags);
  } else if (!result.answered) {
    const stamp = document.createElement("p");
    stamp.className = "no-source";
    stamp.textContent = "No source in these documents";
    node.append(stamp);
  }

  return node;
}

/* ----------------------------------------------------------------- helpers */

// "Ridgeline_Rental_Agreement_2026.pdf" -> "Ridgeline Rental Agreement 2026".
// A trailing "scanned" is dropped because the SCAN badge already says it.
function prettyName(name) {
  return name
    .replace(/\.[^.]+$/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s*scanned\s*$/i, "")
    .trim();
}

function escapeHtml(value) {
  const box = document.createElement("div");
  box.textContent = value ?? "";
  return box.innerHTML;
}

function scrollDown() {
  thread.scrollTop = thread.scrollHeight;
}
