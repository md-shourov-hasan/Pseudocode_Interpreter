// The draggable divider between the Source and Output panes.
//
// The split is stored as the editor pane's share of the workspace (0..1) and
// applied through the --split custom property (see .editor-pane in style.css),
// so it stays proportional when the window is resized. On narrow screens the
// panes stack, and the same share then applies to the height instead.
//
// This file is loaded before Monaco so a saved split is in place before the
// editor is created, rather than the panes jumping once it loads.
(function () {
  const workspace = document.querySelector(".workspace");
  const splitter = document.getElementById("splitter");
  if (!workspace || !splitter) return;

  const STORAGE_KEY = "pseudocode.split";
  const DEFAULT_SPLIT = 1.4 / 2.4; // the original fixed 1.4 : 1 layout
  const MIN_SPLIT = 0.15;
  const MAX_SPLIT = 0.85;
  const KEY_STEP = 0.02;
  const MIN_PANE_WIDTH = 240;
  const MIN_PANE_HEIGHT = 140;

  let split = DEFAULT_SPLIT;

  const isStacked = () =>
    getComputedStyle(workspace).flexDirection === "column";

  // The share range that leaves both panes at least their minimum pixel size
  // (kept in step with the .console-pane minimums in style.css), so the
  // divider stops where the pane stops instead of running on past it.
  function splitLimits() {
    const stacked = isStacked();
    const rect = workspace.getBoundingClientRect();
    const size = stacked ? rect.height : rect.width;
    const minPane = stacked ? MIN_PANE_HEIGHT : MIN_PANE_WIDTH;
    const share = size > 0 ? minPane / size : 0;
    const min = Math.max(MIN_SPLIT, share);
    const max = Math.min(MAX_SPLIT, 1 - share);
    return min <= max ? [min, max] : [0.5, 0.5];
  }

  function applySplit(value) {
    const [min, max] = splitLimits();
    split = Math.min(max, Math.max(min, value));
    workspace.style.setProperty("--split", `${(split * 100).toFixed(2)}%`);
    splitter.setAttribute("aria-valuenow", String(Math.round(split * 100)));
  }

  // Storage can be unavailable (private mode, or blocked when the page is
  // embedded in an iframe); the splitter still works, it just isn't remembered.
  function loadSplit() {
    try {
      const saved = parseFloat(localStorage.getItem(STORAGE_KEY));
      return Number.isFinite(saved) ? saved : DEFAULT_SPLIT;
    } catch (err) {
      return DEFAULT_SPLIT;
    }
  }

  function saveSplit() {
    try {
      localStorage.setItem(STORAGE_KEY, String(split));
    } catch (err) {
      // Not remembered; nothing else to do.
    }
  }

  function updateOrientation() {
    splitter.setAttribute(
      "aria-orientation",
      isStacked() ? "horizontal" : "vertical",
    );
  }

  function splitFromPointer(event) {
    const rect = workspace.getBoundingClientRect();
    return isStacked()
      ? (event.clientY - rect.top) / rect.height
      : (event.clientX - rect.left) / rect.width;
  }

  // Pointer capture keeps the drag going while the pointer is over the editor
  // or outside the window, and covers mouse, touch and pen alike.
  splitter.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add("dragging");
    document.body.classList.add(isStacked() ? "resizing-rows" : "resizing-cols");
  });

  splitter.addEventListener("pointermove", (event) => {
    if (!splitter.hasPointerCapture(event.pointerId)) return;
    applySplit(splitFromPointer(event));
  });

  function endDrag() {
    if (!splitter.classList.contains("dragging")) return;
    splitter.classList.remove("dragging");
    document.body.classList.remove("resizing-cols", "resizing-rows");
    saveSplit();
  }
  splitter.addEventListener("pointerup", endDrag);
  splitter.addEventListener("pointercancel", endDrag);
  splitter.addEventListener("lostpointercapture", endDrag);

  // Double-click restores the original layout.
  splitter.addEventListener("dblclick", () => {
    applySplit(DEFAULT_SPLIT);
    saveSplit();
  });

  splitter.addEventListener("keydown", (event) => {
    const stacked = isStacked();
    const shrinkKey = stacked ? "ArrowUp" : "ArrowLeft";
    const growKey = stacked ? "ArrowDown" : "ArrowRight";
    if (event.key === shrinkKey) applySplit(split - KEY_STEP);
    else if (event.key === growKey) applySplit(split + KEY_STEP);
    else if (event.key === "Home") applySplit(MIN_SPLIT);
    else if (event.key === "End") applySplit(MAX_SPLIT);
    else if (event.key === "Enter") applySplit(DEFAULT_SPLIT);
    else return;
    event.preventDefault();
    saveSplit();
  });

  window.addEventListener("resize", updateOrientation);

  applySplit(loadSplit());
  updateOrientation();
})();
