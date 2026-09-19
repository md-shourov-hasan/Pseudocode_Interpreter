const editorHost = document.getElementById("editor");
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

let editor = null;
let currentRunId = null;
let pollTimer = null;

// ---- status ------------------------------------------------------

function setStatus(state, label) {
  statusDot.className = "status-dot" + (state ? " " + state : "");
  statusLabel.textContent = label;
}

// ---- Monaco editor ------------------------------------------------

function initializeEditor(monaco) {
  const language = window.PseudocodeMonaco;
  if (!language) {
    throw new Error("Pseudocode Monaco language definition failed to load.");
  }

  monaco.languages.register({
    id: language.languageId,
    extensions: language.extensions,
    aliases: language.aliases,
  });

  monaco.languages.setLanguageConfiguration(
    language.languageId,
    language.configuration,
  );
  monaco.languages.setMonarchTokensProvider(
    language.languageId,
    language.language,
  );
  language.registerCompletionProvider(monaco);
  monaco.editor.defineTheme(language.theme.name, language.theme);

  editor = monaco.editor.create(editorHost, {
    value: SAMPLE,
    language: language.languageId,
    theme: language.theme.name,
    automaticLayout: true,
    fontFamily: '"JetBrains Mono", ui-monospace, "SF Mono", Consolas, monospace',
    fontSize: 14,
    lineHeight: 22,
    fontLigatures: false,
    tabSize: 4,
    insertSpaces: true,
    detectIndentation: false,
    autoIndent: "full",
    scrollBeyondLastLine: false,
    minimap: { enabled: false },
    folding: true,
    smoothScrolling: true,
    padding: { top: 14, bottom: 14 },
    renderWhitespace: "selection",
    lineNumbersMinChars: 3,
    roundedSelection: false,
    contextmenu: true,
    // Enter accepts the highlighted suggestion, but only when that changes the
    // text: typing DE + Enter completes to DECLARE, while a fully typed keyword
    // (ENDIF + Enter) just starts a new line. Tab is handled separately below.
    acceptSuggestionOnEnter: "smart",
    acceptSuggestionOnCommitCharacter: false,
    suggest: {
      showWords: false,
    },
  });

  // Enter accepts a suggestion; Tab never does. While the suggestion list is
  // open, Tab closes it and indents as usual.
  editor.addCommand(
    monaco.KeyCode.Tab,
    () => {
      editor.trigger("keyboard", "hideSuggestWidget", null);
      editor.trigger("keyboard", "tab", null);
    },
    "suggestWidgetVisible && textInputFocus",
  );

  runBtn.disabled = false;
  setStatus("", "Idle");
  editor.focus();
}

if (typeof window.require !== "function") {
  setStatus("error", "Editor failed to load");
} else {
  window.require.config({
    paths: {
      vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.56.0/min/vs",
    },
  });

  window.require(["vs/editor/editor.main"], (monaco) => {
    try {
      initializeEditor(monaco);
    } catch (error) {
      console.error(error);
      appendError(null, "Couldn't initialize the pseudocode editor.");
      setStatus("error", "Editor error");
    }
  });
}

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

// ---- run lifecycle -----------------------------------------------------

async function startRun() {
  if (!editor) return;

  clearConsole();
  hideInputRow();
  runBtn.disabled = true;
  setStatus("running", "Running…");

  let res;
  try {
    res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: editor.getValue() }),
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
    finishRun("error", data.state === "timeout" ? "Timed out" : "Error");
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
