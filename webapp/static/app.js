const editorHost = document.getElementById("editor");
const runBtn = document.getElementById("run-btn");
const stopBtn = document.getElementById("stop-btn");
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
let monacoRef = null;
let currentRunId = null;
let pollTimer = null;

const ERROR_MARKER_OWNER = "pseudocode-errors";

// ---- status ------------------------------------------------------

function setStatus(state, label) {
  statusDot.className = "status-dot" + (state ? " " + state : "");
  statusLabel.textContent = label;
}

// ---- Monaco editor ------------------------------------------------

function initializeEditor(monaco) {
  monacoRef = monaco;
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

  const arrowDecorations = editor.createDecorationsCollection();
  const refreshArrows = () => {
    arrowDecorations.set(findAssignmentArrows(editor.getModel(), monaco));
  };
  editor.onDidChangeModelContent(refreshArrows);
  refreshArrows();

  runBtn.disabled = false;
  setStatus("", "Idle");
  editor.focus();
}

// ---- assignment arrow ----------------------------------------------
//
// "<-" is drawn as a single arrow (see .assign-arrow in style.css). Only the
// drawing changes: the text stays the two characters "<-", occupying the same
// two columns, so the cursor, selection, copy/paste, the source sent to the
// server and the error column spans it sends back are all unaffected.

// Columns (0-based) of every "<-" on one line that is an assignment arrow,
// skipping any inside a string, CHAR literal or comment. "<--" is left as
// typed, because the engine reports it as a typo.
function assignmentArrowColumns(line) {
  const columns = [];
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === "/" && line[i + 1] === "/") break;
    if (ch === '"' || ch === "'") {
      const close = line.indexOf(ch, i + 1);
      if (close < 0) break;
      i = close + 1;
    } else if (ch === "<" && line[i + 1] === "-") {
      if (line[i + 2] !== "-") columns.push(i);
      i += 2;
    } else {
      i += 1;
    }
  }
  return columns;
}

function findAssignmentArrows(model, monaco) {
  const decorations = [];
  const options = {
    inlineClassName: "assign-arrow",
    stickiness: monaco.editor.TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
  };
  for (let line = 1; line <= model.getLineCount(); line++) {
    for (const column of assignmentArrowColumns(model.getLineContent(line))) {
      decorations.push({
        range: new monaco.Range(line, column + 1, line, column + 3),
        options,
      });
    }
  }
  return decorations;
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

    // The editor's font (JetBrains Mono) loads asynchronously over the
    // network (see the Google Fonts <link> in index.html). Monaco measures
    // each character's pixel width up front to place the cursor and lay out
    // text, and if that measurement happens before the web font has finished
    // loading, it's measuring the browser's fallback font instead. When
    // JetBrains Mono then swaps in with (very slightly) different character
    // widths, Monaco keeps using its now-stale measurement, so the cursor's
    // computed pixel position drifts further from the real glyph edges with
    // every character typed. document.fonts.ready resolves once every font
    // the page actually used has finished loading, so this reliably fires
    // once, right after the swap, and remeasureFonts() clears the stale
    // cache so cursor placement lines up with the real font from then on.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => monaco.editor.remeasureFonts());
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

// ---- console syntax highlighting ---------------------------------------
//
// The error console re-prints one line of the user's source (see
// appendSourceSpan below). It should look like the same code the editor is
// showing, not plain white text, so it's colorized with the exact same
// token categories and theme colors Monaco uses (window.PseudocodeMonaco's
// Monarch `language` rules and `theme` rules) — a small hand-rolled
// tokenizer that mirrors that Monarch grammar closely enough for a single
// line, rather than spinning up a hidden editor instance just to ask Monaco
// to tokenize a string.

let _pseudocodeThemeColors = null;
function themeColorFor(tokenType) {
  if (!_pseudocodeThemeColors) {
    _pseudocodeThemeColors = {};
    const rules = window.PseudocodeMonaco?.theme?.rules ?? [];
    rules.forEach((rule) => {
      _pseudocodeThemeColors[rule.token] = `#${rule.foreground}`;
    });
  }
  return _pseudocodeThemeColors[tokenType];
}

let _keywordTokenTypes = null;
function keywordTokenType(word) {
  if (!_keywordTokenTypes) {
    _keywordTokenTypes = new Map();
    const lang = window.PseudocodeMonaco?.language;
    if (lang) {
      // Same grouping -> token-type mapping as the Monarch `cases` block in
      // pseudocode-monaco.js, so a keyword always gets the same color here
      // as it does in the editor.
      const groups = [
        [lang.typeKeywords, "type"],
        [lang.controlKeywords, "keyword.control"],
        [lang.declarationKeywords, "keyword.declaration"],
        [lang.ioKeywords, "keyword.io"],
        [lang.arrayKeywords, "keyword.array"],
        [lang.fileKeywords, "keyword.file"],
        [lang.routineKeywords, "keyword.routine"],
        [lang.logicalKeywords, "keyword.operator"],
        [lang.booleanLiterals, "constant.language"],
        [lang.builtinFunctions, "predefined"],
      ];
      groups.forEach(([words, tokenType]) => {
        (words || []).forEach((w) => _keywordTokenTypes.set(w, tokenType));
      });
    }
  }
  return _keywordTokenTypes.get(word);
}

// Ordered the same way as the Monarch tokenizer's `root` rules: comments
// before the divide operator, literals before identifiers, etc.
const _HIGHLIGHT_RULES = [
  [/^\/\/.*/, "comment"],
  [/^'[^'\r\n]*'/, "string"],
  [/^"[^"\r\n]*"/, "string"],
  [/^\d+\.\d+/, "number"],
  [/^\d+/, "number"],
  [/^<-(?!-)/, "assign"], // drawn as an arrow, like in the editor
  [/^(?:<-|\u2190|<>|<=|>=|[+\-*/%^=<>])/, "operator"],
  [/^[()[\]{},:]/, "delimiter"],
  [/^[A-Za-z_][A-Za-z0-9_]*/, "word"], // resolved to a specific token type below
  [/^\s+/, null], // whitespace: no color, inherits the row's default text color
];

// Colorizes one line of pseudocode into a DocumentFragment of <span>s,
// preserving every character (including spaces) so the caret row appended
// underneath it in appendSourceSpan still lines up exactly.
function highlightPseudocodeLine(line) {
  const frag = document.createDocumentFragment();
  const appendSpan = (text, tokenType) => {
    const span = document.createElement("span");
    const color = tokenType && themeColorFor(tokenType);
    if (color) span.style.color = color;
    if (tokenType === "assign") span.className = "assign-arrow";
    span.textContent = text;
    frag.appendChild(span);
  };

  let rest = line;
  while (rest.length > 0) {
    let matched = false;
    for (const [pattern, tokenType] of _HIGHLIGHT_RULES) {
      const m = pattern.exec(rest);
      if (!m) continue;
      const text = m[0];
      appendSpan(text, tokenType === "word" ? keywordTokenType(text) ?? "identifier" : tokenType);
      rest = rest.slice(text.length);
      matched = true;
      break;
    }
    if (!matched) {
      // A character the grammar doesn't recognize — show it plainly rather
      // than dropping it, so the underline below still lines up.
      appendSpan(rest[0], null);
      rest = rest.slice(1);
    }
  }
  return frag;
}

// column/endColumn are the 1-based, inclusive character span of the error
// on `line` (see engine/errors.py's PseudocodeError). Both are undefined
// for errors that don't point at a specific piece of text (e.g. a missing
// ENDIF, or a failure with no source location at all) -- those fall back
// to the line-chip-only rendering this always had.
function appendError(line, message, column, endColumn) {
  if (line && column && editor) {
    appendSourceSpan(line, column, endColumn);
  }

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

// Renders the offending source line followed by a row of "^" carets under
// the exact span that's wrong, e.g.:
//
//   Score <- "hello"
//          ^^^^^^^
//
// so the student sees precisely which piece of text the error is about,
// not just which line. The source line is syntax-highlighted the same way
// the editor above it is (see highlightPseudocodeLine), so it reads as the
// same code rather than a plain-text copy of it.
function appendSourceSpan(line, column, endColumn) {
  const model = editor.getModel();
  if (!model || line < 1 || line > model.getLineCount()) return;

  const sourceLine = model.getLineContent(line);
  const start = Math.max(1, column);
  const end = Math.max(start, endColumn || start);
  const caretCount = end - start + 1;

  const block = document.createElement("pre");
  block.className = "console-line error-span";

  const codeRow = document.createElement("div");
  codeRow.className = "error-span-code";
  codeRow.appendChild(highlightPseudocodeLine(sourceLine));

  const caretRow = document.createElement("div");
  caretRow.className = "error-span-carets";
  caretRow.textContent = " ".repeat(start - 1) + "^".repeat(caretCount);

  block.appendChild(codeRow);
  block.appendChild(caretRow);
  consoleEl.appendChild(block);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

// ---- editor underline (squiggly marker) --------------------------------

function clearErrorMarkers() {
  if (monacoRef && editor) {
    monacoRef.editor.setModelMarkers(editor.getModel(), ERROR_MARKER_OWNER, []);
  }
}

function setErrorMarker(line, message, column, endColumn) {
  if (!monacoRef || !editor || !line || !column) return;
  const end = Math.max(column, endColumn || column);
  monacoRef.editor.setModelMarkers(editor.getModel(), ERROR_MARKER_OWNER, [
    {
      startLineNumber: line,
      startColumn: column,
      endLineNumber: line,
      // Monaco's endColumn is exclusive (one past the last character),
      // while our span's end_column is inclusive -- hence the +1.
      endColumn: end + 1,
      message,
      severity: monacoRef.MarkerSeverity.Error,
    },
  ]);
}

// ---- run lifecycle -----------------------------------------------------

async function startRun() {
  if (!editor) return;

  clearConsole();
  clearErrorMarkers();
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

  const data = await readJson(res);
  if (!res.ok || !data.run_id) {
    // 429/503 mean the server's run limits were reached; the message says
    // to wait and try again.
    appendError(null, data.error || "Couldn't start the program.");
    finishRun("error", res.status === 429 || res.status === 503 ? "Busy" : "Error");
    return;
  }

  currentRunId = data.run_id;
  pollFailures = 0;
  stopBtn.disabled = false;
  schedulePoll(currentRunId);
}

// Stop pressed: end the run now. Clearing currentRunId first makes any poll
// still in flight discard its result, so nothing more is printed after the
// "stopped" line; the server is then told to kill the program.
function stopRun() {
  const runId = currentRunId;
  if (!runId) return;

  currentRunId = null;
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  appendLine("The program has been stopped by the user", "stopped-line");
  finishRun("error", "Stopped");

  // If this request fails, the server still stops the run by itself once it
  // notices nobody is polling it any more.
  fetch(`/api/run/${runId}/cancel`, { method: "POST" }).catch(() => {});
}

// A response body that isn't JSON (e.g. a proxy error page) must not throw.
async function readJson(res) {
  try {
    return await res.json();
  } catch (err) {
    return {};
  }
}

// Polls run one after another (never overlapping), so events are always
// appended in order. Each poll is a long-poll: the server holds it for up to
// POLL_WAIT_SECONDS until something happens, so an idle or INPUT-waiting
// program costs about one request a second rather than several. When events
// did arrive, the next poll waits POLL_BATCH_MS first, so a program that
// OUTPUTs continuously is fetched in batches instead of one line per request.
const POLL_WAIT_SECONDS = 1.5;
const POLL_BATCH_MS = 150;
const MAX_POLL_FAILURES = 5;
let pollFailures = 0;

function schedulePoll(runId, delayMs = 0) {
  pollTimer = setTimeout(() => poll(runId), delayMs);
}

async function poll(runId) {
  pollTimer = null;
  if (runId !== currentRunId) return;

  let res;
  try {
    res = await fetch(`/api/run/${runId}/poll?wait=${POLL_WAIT_SECONDS}`);
  } catch (err) {
    // Ride out a brief network blip rather than abandoning the run.
    if (++pollFailures >= MAX_POLL_FAILURES) {
      currentRunId = null;
      appendError(null, "Lost the connection to the compiler server.");
      finishRun("error", "Error");
    } else if (runId === currentRunId) {
      schedulePoll(runId, 1000);
    }
    return;
  }
  if (runId !== currentRunId) return;
  if (!res.ok) {
    currentRunId = null;
    appendError(null, "Lost track of the running program.");
    finishRun("error", "Error");
    return;
  }
  pollFailures = 0;
  const data = await readJson(res);

  for (const event of data.events || []) {
    if (event.type === "output") {
      appendLine(event.text);
    } else if (event.type === "waiting") {
      showInputRow();
    } else if (event.type === "error") {
      appendError(event.line, event.message, event.column, event.end_column);
      setErrorMarker(event.line, event.message, event.column, event.end_column);
    } else if (event.type === "done") {
      appendLine("Program finished.", "done-line");
    }
  }

  if (data.state === "finished") {
    currentRunId = null;
    finishRun("done", "Finished");
  } else if (data.state === "error" || data.state === "timeout" || data.state === "cancelled") {
    currentRunId = null;
    finishRun("error", data.state === "timeout" ? "Timed out" : data.state === "cancelled" ? "Stopped" : "Error");
  } else {
    schedulePoll(runId, (data.events || []).length ? POLL_BATCH_MS : 0);
  }
}

function finishRun(state, label) {
  runBtn.disabled = false;
  stopBtn.disabled = true;
  hideInputRow();
  setStatus(state, label);
}

// When the SudoLab page navigates away (or the tab closes), the iframe is
// unloaded: tell the server so it stops the run now instead of waiting for
// the abandoned-run timeout. sendBeacon is the only request that reliably
// survives page unload.
window.addEventListener("pagehide", () => {
  if (currentRunId && navigator.sendBeacon) {
    navigator.sendBeacon(`/api/run/${currentRunId}/cancel`);
  }
});

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
  if (!currentRunId || inputRow.classList.contains("hidden")) return;
  const value = inputField.value;
  appendLine("> " + value, "waiting-marker");
  hideInputRow();
  setStatus("running", "Running…");
  let res;
  try {
    res = await fetch(`/api/run/${currentRunId}/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
  } catch (err) {
    appendError(null, "Couldn't send that value to the compiler server.");
    showInputRow();
    return;
  }
  if (res.status === 413) {
    // Too long: the program is still waiting, so let the student retry.
    const data = await readJson(res);
    appendError(null, data.error || "That value is too long.");
    showInputRow();
  }
  // Any other refusal (409: the run already ended) is reported by the
  // next poll, which carries the run's final state.
});

runBtn.addEventListener("click", startRun);
stopBtn.addEventListener("click", stopRun);
