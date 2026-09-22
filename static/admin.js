/*
  The owner's desk.

  Two jobs: keep the documents current, and show what staff asked - especially
  the questions the documents could not answer, which is the list worth acting on.
*/

const documentsBody = document.getElementById("documents");
const uploadStatus = document.getElementById("upload-status");
const fileInput = document.getElementById("file");
const drop = document.getElementById("drop");

load();

/* ------------------------------------------------------------------ loading */

async function load() {
  const overview = await fetch("/api/admin/overview").then((r) => r.json());

  document.getElementById("company").textContent = overview.company;
  document.getElementById("doc-count").textContent =
    `${overview.documents.length} documents · ${overview.passages} passages indexed`;
  document.getElementById("drop-note").textContent =
    `Drag a file here, or click to choose. PDF, Word or text, up to ${overview.max_upload_mb} MB.`;

  drawDocuments(overview.documents);
  drawCounts(overview.summary, overview.logging);
  drawGaps(overview.summary.gaps);
  await drawAsked();
}

function drawDocuments(documents) {
  documentsBody.innerHTML = "";
  for (const doc of documents) {
    const scanned = /scan/i.test(doc.name);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><a href="${doc.url}" target="_blank" rel="noopener">${escapeHtml(prettyName(doc.name))}</a></td>
      <td class="kind-cell ${scanned ? "scan" : ""}">${scanned ? "SCAN" : doc.type}</td>
      <td class="right">${doc.pages || "-"}</td>
      <td class="right">${doc.passages}</td>
      <td class="right"><button class="remove" data-path="${escapeHtml(doc.path)}"
          data-name="${escapeHtml(prettyName(doc.name))}">Remove</button></td>`;
    documentsBody.append(row);
  }
}

function drawCounts(summary, logging) {
  const tiles = document.getElementById("tiles");
  if (!logging) {
    document.getElementById("log-note").textContent = "recording is switched off";
    tiles.innerHTML = `<p class="empty">Question recording is off (LOG_QUESTIONS=false in .env).</p>`;
    return;
  }
  tiles.innerHTML = `
    <div class="tile"><b>${summary.total}</b><span>questions asked</span></div>
    <div class="tile"><b>${summary.answered}</b><span>answered from your documents</span></div>
    <div class="tile gap"><b>${summary.unanswered}</b><span>not covered</span></div>`;
}

function drawGaps(gaps) {
  const list = document.getElementById("gaps");
  list.innerHTML = "";
  if (!gaps.length) {
    list.innerHTML = `<p class="empty">Nothing yet. Every question so far was answered from your documents.</p>`;
    return;
  }
  for (const gap of gaps) {
    list.insertAdjacentHTML("beforeend",
      `<li><span class="times">${gap.times}x</span><span>${escapeHtml(gap.question)}</span></li>`);
  }
}

async function drawAsked() {
  const onlyUnanswered = document.getElementById("only-unanswered").checked;
  const data = await fetch(`/api/admin/questions?only_unanswered=${onlyUnanswered}&limit=60`)
    .then((r) => r.json());
  const list = document.getElementById("asked");
  list.innerHTML = "";
  if (!data.questions.length) {
    list.innerHTML = `<p class="empty">No questions recorded yet.</p>`;
    return;
  }
  for (const q of data.questions) {
    const sources = q.sources ? `<span class="sources">${escapeHtml(q.sources)}</span>` : "";
    const flag = q.answered ? "" : `<span class="no">no answer</span>`;
    list.insertAdjacentHTML("beforeend", `
      <li>
        <span class="q">${escapeHtml(q.question)}${flag}${sources}</span>
        <span class="when">${escapeHtml(shortDate(q.asked_at))} · ${escapeHtml(q.channel)}</span>
      </li>`);
  }
}

document.getElementById("only-unanswered").addEventListener("change", drawAsked);

/* ----------------------------------------------------------------- uploading */

drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => fileInput.files[0] && upload(fileInput.files[0]));

// Dragging a file onto the box is how most people will do this.
for (const event of ["dragenter", "dragover"]) {
  drop.addEventListener(event, (e) => { e.preventDefault(); drop.classList.add("over"); });
}
for (const event of ["dragleave", "drop"]) {
  drop.addEventListener(event, (e) => { e.preventDefault(); drop.classList.remove("over"); });
}
drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));

async function upload(file) {
  say("busy", `Reading ${file.name}…`);
  const body = new FormData();
  body.append("file", file);

  try {
    const response = await fetch("/api/admin/documents", { method: "POST", body });
    const result = await response.json();
    if (!response.ok) {
      say("bad", result.detail || "That file could not be added.");
      return;
    }
    const where = result.pages ? `${result.pages} pages, ` : "";
    say("ok", `${result.replaced ? "Replaced" : "Added"} ${result.name} (${where}${result.passages} passages). ` +
              `Staff can ask about it now.`);
    await load();
  } catch {
    say("bad", "Could not reach the assistant. Is it still running?");
  } finally {
    fileInput.value = "";
  }
}

documentsBody.addEventListener("click", async (event) => {
  const button = event.target.closest(".remove");
  if (!button) return;
  // Removing a document is the one destructive action here, so it asks first.
  if (!confirm(`Remove "${button.dataset.name}"?\n\nIt will no longer be used for answers. ` +
               `The file is deleted from the documents folder.`)) return;

  say("busy", "Removing…");
  const response = await fetch(`/api/admin/documents/${encodeURI(button.dataset.path)}`,
                               { method: "DELETE" });
  if (response.ok) {
    say("ok", `Removed ${button.dataset.name}.`);
    await load();
  } else {
    say("bad", "That document could not be removed.");
  }
});

function say(kind, message) {
  uploadStatus.hidden = false;
  uploadStatus.className = `status ${kind}`;
  uploadStatus.textContent = message;
}

/* ------------------------------------------------------------------ helpers */

function prettyName(name) {
  return name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").replace(/\s*scanned\s*$/i, "").trim();
}

function shortDate(value) {
  const date = new Date(value);
  return isNaN(date) ? value : date.toLocaleString(undefined,
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(value) {
  const box = document.createElement("div");
  box.textContent = value ?? "";
  return box.innerHTML;
}
