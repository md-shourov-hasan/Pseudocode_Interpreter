const editor = document.getElementById("editor");
const gutter = document.getElementById("gutter");
const runBtn = document.getElementById("run-btn");
const statusDot = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const consoleEl = document.getElementById("console");
const inputRow = document.getElementById("input-row");
const inputField = document.getElementById("input-field");

const SAMPLE = `// Try running this, or write your own pseudocode.
DECLARE Answer : INTEGER
DECLARE CorrectAnswer : INTEGER
DECLARE Score : INTEGER

CorrectAnswer <- 12
Score <- 0

OUTPUT "What is 7 + 5?"
INPUT Answer

IF Answer = CorrectAnswer THEN
    Score <- Score + 1
    OUTPUT "Correct!"
ELSE
    OUTPUT "Not quite - the answer was ", CorrectAnswer
ENDIF

OUTPUT "Score: ", Score
`;

let currentRunId = null;
let pollTimer = null;

// ---- editor gutter --------------------------------------------------

function syncGutter() {
  const lineCount = editor.value.split("\n").length;
  const lines = [];
  for (let i = 1; i <= lineCount; i++) lines.push(i);
  gutter.textContent = lines.join("\n");
}

// ---- smart-punctuation sanitizer ------------------------------------
//
// Some browsers/OSes (Safari's "Smart Dashes"/"Smart Quotes", mobile
// keyboard autocorrect, Grammarly-style extensions) silently rewrite
// plain ASCII as you type — e.g. turning "-" into an en/em dash, or
// straight quotes into curly ones. That breaks pseudocode syntax like
// the "<-" assignment arrow or string literals. This normalizes those
// characters back to plain ASCII on every keystroke, keeping the
// cursor position stable (every substitution below is one-character-
// for-one-character, so offsets never shift).
const SMART_PUNCTUATION = {
  "\u2013": "-", // en dash
  "\u2014": "-", // em dash
  "\u2018": "'", "\u2019": "'", // curly single quotes
  "\u201C": '"', "\u201D": '"', // curly double quotes
};
const SMART_PUNCTUATION_RE = /[\u2013\u2014\u2018\u2019\u201C\u201D]/g;

function sanitizeSmartPunctuation() {
  const original = editor.value;
  if (!SMART_PUNCTUATION_RE.test(original)) return;
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  editor.value = original.replace(SMART_PUNCTUATION_RE, (ch) => SMART_PUNCTUATION[ch]);
  editor.selectionStart = start;
  editor.selectionEnd = end;
}

editor.addEventListener("input", () => {
  sanitizeSmartPunctuation();
  syncGutter();
});
editor.addEventListener("scroll", () => {
  gutter.scrollTop = editor.scrollTop;
});

// ---- Tab / Enter smart indentation ------------------------------------
//
// Indentation unit is 4 spaces. Tab/Shift+Tab indent or outdent the
// current line (or every line touched by a selection). Enter carries
// the current line's indentation forward, and adds one extra level
// when the line being finished ends with THEN (an IF block is being
// opened) — more block-opening keywords (loops, etc.) will extend this
// same rule as those constructs are added.
const INDENT = "    ";
const INDENT_TRIGGERS = [/\bTHEN\s*$/, /\bELSE\s*$/];

function lineStart(text, pos) {
  return text.lastIndexOf("\n", pos - 1) + 1;
}

function lineEnd(text, pos) {
  const i = text.indexOf("\n", pos);
  return i === -1 ? text.length : i;
}

function insertText(text) {
  // Prefer execCommand so the browser's native undo stack keeps working;
  // fall back to direct value manipulation if it's unavailable.
  if (document.execCommand && document.execCommand("insertText", false, text)) {
    return;
  }
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  editor.value = editor.value.slice(0, start) + text + editor.value.slice(end);
  editor.selectionStart = editor.selectionEnd = start + text.length;
}

function handleEnterKey() {
  const value = editor.value;
  const pos = editor.selectionStart;
  const currentLineStart = lineStart(value, pos);
  const currentLine = value.slice(currentLineStart, pos);
  const indentMatch = currentLine.match(/^[ \t]*/);
  let indent = indentMatch ? indentMatch[0] : "";

  const trimmed = currentLine.trim();
  if (INDENT_TRIGGERS.some((re) => re.test(trimmed))) {
    indent += INDENT;
  }

  insertText("\n" + indent);
}

function handleTabKey(shiftKey) {
  const value = editor.value;
  const selStart = editor.selectionStart;
  const selEnd = editor.selectionEnd;
  const hasSelection = selStart !== selEnd;
  const spansMultipleLines = hasSelection && value.slice(selStart, selEnd).includes("\n");

  if (!hasSelection && !shiftKey) {
    insertText(INDENT);
    return;
  }

  if (!spansMultipleLines && !shiftKey) {
    insertText(INDENT);
    return;
  }

  // Indent/outdent every full line touched by the selection (or just the
  // current line for a plain Shift+Tab with no selection).
  const blockStart = lineStart(value, selStart);
  const blockEnd = hasSelection ? lineEnd(value, selEnd) : lineEnd(value, selStart);
  const block = value.slice(blockStart, blockEnd);
  const lines = block.split("\n");

  let firstLineDelta = 0;
  let lastLineDelta = 0;

  const newLines = lines.map((line, idx) => {
    if (shiftKey) {
      const removed = line.match(/^( {1,4}|\t)/);
      if (!removed) return line;
      if (idx === 0) firstLineDelta = -removed[0].length;
      if (idx === lines.length - 1) lastLineDelta = -removed[0].length;
      return line.slice(removed[0].length);
    }
    if (idx === 0) firstLineDelta = INDENT.length;
    if (idx === lines.length - 1) lastLineDelta = INDENT.length;
    return INDENT + line;
  });

  const newBlock = newLines.join("\n");
  editor.value = value.slice(0, blockStart) + newBlock + value.slice(blockEnd);
  editor.selectionStart = Math.max(blockStart, selStart + firstLineDelta);
  editor.selectionEnd = Math.max(blockStart, selEnd + lastLineDelta);
  syncGutter();
}

editor.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    handleTabKey(e.shiftKey);
  } else if (e.key === "Enter") {
    e.preventDefault();
    handleEnterKey();
  }
});

editor.value = SAMPLE;
syncGutter();

// ---- console rendering --------------------------------------------------

function clearConsole() {
  consoleEl.innerHTML = "";
}

function appendLine(text, className) {
  const div = document.createElement("div");
  div.className = "console-line" + (className ? " " + className : "");
  div.textContent = text;
  consoleEl.appendChild(div);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

function appendError(line, message) {
  const wrap = document.createElement("div");
  wrap.className = "console-line error-line";
  const chip = document.createElement("span");
  chip.className = "line-chip";
  chip.textContent = line ? `Line ${line}` : "Error";
  const msg = document.createElement("span");
  msg.textContent = message;
  wrap.appendChild(chip);
  wrap.appendChild(msg);
  consoleEl.appendChild(wrap);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ---- status ------------------------------------------------------

function setStatus(state, label) {
  statusDot.className = "status-dot" + (state ? " " + state : "");
  statusLabel.textContent = label;
}

// ---- run lifecycle -----------------------------------------------------

async function startRun() {
  clearConsole();
  hideInputRow();
  runBtn.disabled = true;
  setStatus("running", "Running…");

  let res;
  try {
    res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: editor.value }),
    });
  } catch (err) {
    appendError(null, "Couldn't reach the compiler server.");
    finishRun("error", "Error");
    return;
  }

  const data = await res.json();
  if (!res.ok) {
    appendError(null, data.error || "Couldn't start the program.");
    finishRun("error", "Error");
    return;
  }

  currentRunId = data.run_id;
  pollTimer = setInterval(poll, 150);
}

async function poll() {
  if (!currentRunId) return;
  const res = await fetch(`/api/run/${currentRunId}/poll`);
  if (!res.ok) {
    stopPolling();
    appendError(null, "Lost track of the running program.");
    finishRun("error", "Error");
    return;
  }
  const data = await res.json();

  for (const event of data.events) {
    if (event.type === "output") {
      appendLine(event.text);
    } else if (event.type === "waiting") {
      showInputRow();
    } else if (event.type === "error") {
      appendError(event.line, event.message);
    } else if (event.type === "done") {
      appendLine("Program finished.", "done-line");
    }
  }

  if (data.state === "finished") {
    stopPolling();
    finishRun("done", "Finished");
  } else if (data.state === "error" || data.state === "timeout") {
    stopPolling();
    finishRun("error", "Error");
  }
}

function finishRun(state, label) {
  runBtn.disabled = false;
  hideInputRow();
  setStatus(state, label);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// ---- input row --------------------------------------------------------

function showInputRow() {
  setStatus("waiting", "Waiting for input…");
  inputRow.classList.remove("hidden");
  inputField.value = "";
  inputField.focus();
}

function hideInputRow() {
  inputRow.classList.add("hidden");
}

inputRow.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentRunId) return;
  const value = inputField.value;
  appendLine("> " + value, "waiting-marker");
  hideInputRow();
  setStatus("running", "Running…");
  await fetch(`/api/run/${currentRunId}/input`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
});

runBtn.addEventListener("click", startRun);
