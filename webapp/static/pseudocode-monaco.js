/*
 * Monaco language definition for Cambridge/IGCSE-style pseudocode.
 *
 * This file contains editor-facing language intelligence only: syntax
 * colorization, keyword classification, bracket behavior, indentation, and
 * context-aware completion (see buildCompletionEngine).
 * The compiler's Python lexer/parser remain the source of truth for actual
 * language validation and execution.
 *
 * Monaco Editor 0.56.0 is loaded by index.html. The AMD loader is used here
 * because the current Flask application does not have a frontend bundler yet.
 * Monaco has deprecated AMD in favor of ESM, so this is intentionally kept as
 * a migration-friendly adapter rather than being coupled to application code.
 */

/*
 * Context-aware completion engine.
 *
 * Given the source text that precedes the word being typed, work out what the
 * grammar allows at that point and return only those candidates:
 *
 *   - which variables, constants and arrays have been DECLAREd so far (and
 *     their types, so e.g. FOR bounds only offer numeric names),
 *   - which block (IF / FOR / WHILE / REPEAT / CASE) is innermost and open,
 *     so only its closing keyword is offered,
 *   - where the cursor sits inside the current statement (after DECLARE x :
 *     a data type is expected, after INPUT a variable, after FOR ... TO a
 *     STEP, and so on).
 *
 * It is deliberately a lightweight, editor-side approximation. It never
 * replaces the Python lexer/parser, which stay the source of truth for
 * whether a program is actually valid. The function is pure (text in,
 * candidates out) and takes no Monaco dependency, so it can be unit-tested.
 */
function buildCompletionEngine(lang, table) {
  const meta = new Map(table.map((item) => [item.label, item]));
  const KEYWORDS = new Set([
    ...lang.controlKeywords, ...lang.declarationKeywords, ...lang.ioKeywords,
    ...lang.arrayKeywords, ...lang.typeKeywords, ...lang.fileKeywords,
    ...lang.routineKeywords, ...lang.logicalKeywords,
  ]);
  const TYPES = lang.typeKeywords;
  const BUILTINS = new Set(lang.builtinFunctions);
  const BOOLEANS = new Set(lang.booleanLiterals);

  // Keywords the grammar has, but the interpreter does not run yet (README
  // milestone 9). They are still offered, ranked last and labelled.
  const NOT_YET = new Set(["OPENFILE", "READFILE", "WRITEFILE", "CLOSEFILE"]);
  // Always-valid statement starters, offered at the start of any line.
  // PROCEDURE/FUNCTION are deliberately NOT here: the grammar only allows
  // them at the very top of the program (see scanDefinitions), so offering
  // them as an ordinary mid-program statement would just set the student up
  // for a "must be at the top of the program" error from the real compiler.
  const STATEMENT_KEYWORDS = [
    "DECLARE", "CONSTANT", "INPUT", "OUTPUT", "IF", "CASE", "FOR", "REPEAT", "WHILE", "CALL",
  ];
  // After one of these, a new statement may follow on the same line.
  const STATEMENT_STARTERS = new Set(["THEN", "ELSE", "DO", "OTHERWISE", "REPEAT"]);

  // What each built-in returns, and what type each of its arguments takes.
  const RETURNS = {
    ROUND: "numeric", RANDOM: "numeric", DIV: "numeric", MOD: "numeric",
    LENGTH: "numeric", LCASE: "string", UCASE: "string", SUBSTRING: "string",
  };
  const ARGUMENTS = {
    ROUND: ["numeric", "numeric"], RANDOM: [], DIV: ["numeric", "numeric"],
    MOD: ["numeric", "numeric"], LENGTH: ["string"], LCASE: ["string"],
    UCASE: ["string"], SUBSTRING: ["string", "numeric", "numeric"],
  };
  const CATEGORY = {
    INTEGER: "numeric", REAL: "numeric", STRING: "string", CHAR: "string", BOOLEAN: "boolean",
  };

  // ---- tokenizer ---------------------------------------------------------
  // Token shapes: {t:"nl"} {t:"kw",v} {t:"id",v} {t:"lit",v,lit}
  // {t:"assign"} {t:"op",v} and punctuation tokens whose t is the character.
  function tokenize(text) {
    const toks = [];
    const n = text.length;
    const isDigit = (c) => c >= "0" && c <= "9";
    const isWordStart = (c) => /[A-Za-z_]/.test(c);
    const isWordChar = (c) => /[A-Za-z0-9_]/.test(c);
    let i = 0;
    while (i < n) {
      const ch = text[i];
      if (ch === "\n") { toks.push({ t: "nl" }); i += 1; continue; }
      if (ch === " " || ch === "\t" || ch === "\r") { i += 1; continue; }
      if (ch === "/" && text[i + 1] === "/") {
        while (i < n && text[i] !== "\n") i += 1;
        continue;
      }
      if (ch === '"' || ch === "'") {
        let j = i + 1;
        while (j < n && text[j] !== ch && text[j] !== "\n") j += 1;
        const closed = j < n && text[j] === ch;
        toks.push({ t: "lit", v: text.slice(i, closed ? j + 1 : j), lit: ch === '"' ? "STRING" : "CHAR" });
        i = closed ? j + 1 : j;
        continue;
      }
      if (isDigit(ch)) {
        let j = i;
        while (j < n && isDigit(text[j])) j += 1;
        let lit = "INTEGER";
        if (text[j] === "." && isDigit(text[j + 1] || "")) {
          j += 1;
          while (j < n && isDigit(text[j])) j += 1;
          lit = "REAL";
        }
        toks.push({ t: "lit", v: text.slice(i, j), lit });
        i = j;
        continue;
      }
      if (isWordStart(ch)) {
        let j = i;
        while (j < n && isWordChar(text[j])) j += 1;
        const word = text.slice(i, j);
        if (BOOLEANS.has(word)) toks.push({ t: "lit", v: word, lit: "BOOLEAN" });
        else if (KEYWORDS.has(word)) toks.push({ t: "kw", v: word });
        else toks.push({ t: "id", v: word });
        i = j;
        continue;
      }
      if (ch === "\u2190" || (ch === "<" && text[i + 1] === "-")) {
        toks.push({ t: "assign" });
        i += ch === "<" ? 2 : 1;
        continue;
      }
      if (ch === "<" && (text[i + 1] === ">" || text[i + 1] === "=")) {
        toks.push({ t: "op", v: text.slice(i, i + 2) });
        i += 2;
        continue;
      }
      if (ch === ">" && text[i + 1] === "=") {
        toks.push({ t: "op", v: ">=" });
        i += 2;
        continue;
      }
      if ("+-*/^=<>".includes(ch)) { toks.push({ t: "op", v: ch }); i += 1; continue; }
      if ("()[],:".includes(ch)) { toks.push({ t: ch, v: ch }); i += 1; continue; }
      i += 1; // anything else is ignored; the Python lexer reports it on Run
    }
    return toks;
  }

  // ---- declarations ------------------------------------------------------
  // name -> {name, kind: "var" | "const" | "array", type, bounds}
  // Parses the "(<param>, ...)" clause starting at toks[start] (expected to
  // be "(", the '(' right after a PROCEDURE/FUNCTION name). If there's no
  // "(" there at all (a definition with no parameters, or one where the
  // parameter list hasn't been typed yet), returns no params and leaves
  // `next` at `start`. Shared by collectRoutines (which only needs
  // name/type/isArray, for CALL/expression argument matching) and
  // collectSymbols (which also wants `bounds`, to show a proper
  // "ARRAY[1:10] OF INTEGER" detail for a parameter the same way a
  // DECLAREd array gets one).
  function parseParamClause(toks, start) {
    const params = [];
    // No "(" at all is a complete, paren-less header (a PROCEDURE/FUNCTION
    // may have zero parameters) -- closed: true, distinct from a "(" that's
    // been opened but not yet closed with ")" below.
    if (!(toks[start] && toks[start].t === "(")) return { params, next: start, closed: true };
    let j = start + 1;
    while (toks[j] && toks[j].t !== ")" && toks[j].t !== "nl") {
      if (toks[j].t !== "id") { j += 1; continue; }
      const pname = toks[j].v;
      let type = null;
      let isArray = false;
      let bounds = "";
      const afterColon = toks[j + 1] && toks[j + 1].t === ":" ? toks[j + 2] : null;
      if (afterColon && afterColon.t === "kw" && afterColon.v === "ARRAY") {
        // ARRAY[...] OF <type> -- an extension beyond the SRS's literal
        // grammar (parameters can carry arrays, passed by reference).
        isArray = true;
        let k = j + 3;
        if (toks[k] && toks[k].t === "[") {
          const boundsStart = k + 1;
          let depth = 1;
          k += 1;
          while (toks[k] && depth > 0) {
            if (toks[k].t === "[") depth += 1;
            else if (toks[k].t === "]") depth -= 1;
            k += 1;
          }
          bounds = toks.slice(boundsStart, k - 1).map((x) => x.v || (x.t === "assign" ? "<-" : x.t)).join("");
        }
        if (
          toks[k] && toks[k].t === "kw" && toks[k].v === "OF" &&
          toks[k + 1] && toks[k + 1].t === "kw" && TYPES.includes(toks[k + 1].v)
        ) {
          type = toks[k + 1].v;
          k += 2;
        }
        j = k;
      } else if (afterColon && afterColon.t === "kw" && TYPES.includes(afterColon.v)) {
        type = afterColon.v;
        j += 3;
      } else {
        j += 1;
      }
      params.push({ name: pname, type, isArray, bounds });
    }
    const closed = !!(toks[j] && toks[j].t === ")");
    if (closed) j += 1;
    return { params, next: j, closed };
  }

  // Symbols visible at the CURRENT position (the end of `toks`), following
  // the interpreter's own Milestone 8 scoping rules (see interpreter.py's
  // module docstring): outside any PROCEDURE/FUNCTION, this is the main
  // program's own DECLAREs/CONSTANTs. Inside one, it's instead THAT
  // definition's own parameters and its own local DECLAREs/CONSTANTs, plus
  // (read-only) any CONSTANT declared at the top level -- a global
  // *variable* is never visible inside a definition, and a definition's own
  // locals are never visible outside it (or inside any other definition).
  // PROCEDURE/FUNCTION frames never nest (see analyzeBlocks), so a single
  // depth flag is enough to track "which scope is currently active", and
  // each new definition starts with a completely fresh Map -- an earlier
  // definition's locals are discarded the moment its ENDPROCEDURE/
  // ENDFUNCTION is seen, exactly like a real call frame is.
  function collectSymbols(toks) {
    const globalSymbols = new Map();
    let localSymbols = null; // the routine's own scope, seeded as soon as its header is parsed
    let bodyStart = Infinity; // token index where that scope actually becomes active
    // Local scope activates at the start of the BODY, not at the PROCEDURE/
    // FUNCTION keyword: a parameter's own array-bound expression is (like
    // the interpreter's Interpreter._bind_array_argument) evaluated in the
    // CALLER's scope, so a global variable must still resolve there even
    // though it's textually between PROCEDURE and the body.
    const activeScope = (i) => (localSymbols && i >= bodyStart ? localSymbols : globalSymbols);

    for (let i = 0; i < toks.length; i += 1) {
      const tk = toks[i];
      if (tk.t === "kw" && (tk.v === "PROCEDURE" || tk.v === "FUNCTION")) {
        const isFunction = tk.v === "FUNCTION";
        localSymbols = new Map();
        bodyStart = Infinity; // stays unreachable until the header below is fully parsed
        const nameTok = toks[i + 1];
        if (nameTok && nameTok.t === "id") {
          const { params, next, closed } = parseParamClause(toks, i + 2);
          for (const p of params) {
            localSymbols.set(p.name, p.isArray
              ? { name: p.name, kind: "array", type: p.type, bounds: p.bounds }
              : { name: p.name, kind: "var", type: p.type });
          }
          if (closed) {
            let headerEnd = next;
            if (isFunction && toks[headerEnd] && toks[headerEnd].t === "kw" && toks[headerEnd].v === "RETURNS") {
              headerEnd += 1;
              if (toks[headerEnd] && toks[headerEnd].t === "kw" && TYPES.includes(toks[headerEnd].v)) headerEnd += 1;
            }
            bodyStart = headerEnd;
          } // else: parameter list isn't closed yet, so bodyStart stays Infinity
        }
        continue;
      }
      if (tk.t === "kw" && (tk.v === "ENDPROCEDURE" || tk.v === "ENDFUNCTION")) {
        localSymbols = null;
        bodyStart = Infinity;
        continue;
      }
      if (tk.t === "kw" && tk.v === "DECLARE") {
        const names = [];
        let j = i + 1;
        while (toks[j] && toks[j].t === "id") {
          names.push(toks[j].v);
          j += 1;
          if (toks[j] && toks[j].t === ",") j += 1;
          else break;
        }
        if (!names.length || !(toks[j] && toks[j].t === ":")) continue;
        j += 1;
        if (toks[j] && toks[j].t === "kw" && toks[j].v === "ARRAY") {
          j += 1;
          if (!(toks[j] && toks[j].t === "[")) continue;
          const boundsStart = j + 1;
          let depth = 0;
          for (; toks[j]; j += 1) {
            if (toks[j].t === "[") depth += 1;
            else if (toks[j].t === "]") { depth -= 1; if (depth === 0) break; }
            else if (toks[j].t === "nl") break;
          }
          if (!(toks[j] && toks[j].t === "]")) continue;
          const bounds = toks.slice(boundsStart, j).map((x) => x.v || (x.t === "assign" ? "<-" : x.t)).join("");
          const of = toks[j + 1];
          const type = toks[j + 2];
          if (of && of.t === "kw" && of.v === "OF" && type && type.t === "kw" && TYPES.includes(type.v)) {
            for (const name of names) activeScope(i).set(name, { name, kind: "array", type: type.v, bounds });
          }
        } else if (toks[j] && toks[j].t === "kw" && TYPES.includes(toks[j].v)) {
          for (const name of names) activeScope(i).set(name, { name, kind: "var", type: toks[j].v });
        }
      } else if (tk.t === "kw" && tk.v === "CONSTANT") {
        const name = toks[i + 1];
        if (name && name.t === "id" && toks[i + 2] && toks[i + 2].t === "assign") {
          const value = toks[i + 3];
          activeScope(i).set(name.v, {
            name: name.v, kind: "const", type: value && value.t === "lit" ? value.lit : null,
          });
        }
      }
    }

    if (!(localSymbols && toks.length >= bodyStart)) return globalSymbols; // cursor is at the top level, or still inside a header
    const visible = new Map();
    for (const [name, sym] of globalSymbols) if (sym.kind === "const") visible.set(name, sym);
    for (const [name, sym] of localSymbols) visible.set(name, sym); // locals may shadow a same-named global constant
    return visible;
  }

  // ---- open blocks -------------------------------------------------------
  function analyzeBlocks(toks) {
    const stack = [];
    let pendingThen = false; // IF <cond> seen, THEN not yet (THEN may start the next line)
    let pendingDo = false;
    let atLineStart = true;
    const close = (type) => {
      for (let k = stack.length - 1; k >= 0; k -= 1) {
        if (stack[k].type === type) { stack.splice(k); return; }
      }
    };
    for (let i = 0; i < toks.length; i += 1) {
      const tk = toks[i];
      if (tk.t === "nl") { atLineStart = true; continue; }
      if (atLineStart) {
        atLineStart = false;
        if (!(tk.t === "kw" && tk.v === "THEN")) pendingThen = false;
        if (!(tk.t === "kw" && tk.v === "DO")) pendingDo = false;
      }
      if (tk.t !== "kw") continue;
      const prev = toks[i - 1];
      switch (tk.v) {
        case "IF": stack.push({ type: "IF", hasElse: false }); pendingThen = true; break;
        case "THEN": pendingThen = false; break;
        case "ELSE": {
          const top = stack[stack.length - 1];
          if (top && top.type === "IF") top.hasElse = true;
          break;
        }
        case "ENDIF": close("IF"); break;
        case "FOR": {
          // "OPENFILE x FOR READ" also contains FOR; only a statement-initial
          // FOR opens a loop.
          const initial = !prev || prev.t === "nl" || prev.t === ":" ||
            (prev.t === "kw" && STATEMENT_STARTERS.has(prev.v));
          if (initial) {
            const v = toks[i + 1];
            stack.push({ type: "FOR", variable: v && v.t === "id" ? v.v : null });
          }
          break;
        }
        case "NEXT": close("FOR"); break;
        case "WHILE": stack.push({ type: "WHILE" }); pendingDo = true; break;
        case "DO": pendingDo = false; break;
        case "ENDWHILE": close("WHILE"); break;
        case "REPEAT": stack.push({ type: "REPEAT" }); break;
        case "UNTIL": close("REPEAT"); break;
        case "CASE": {
          const subject = toks[i + 2];
          stack.push({ type: "CASE", subject: subject && subject.t === "id" ? subject.v : null, hasOtherwise: false });
          break;
        }
        case "OTHERWISE": {
          const top = stack[stack.length - 1];
          if (top && top.type === "CASE") top.hasOtherwise = true;
          break;
        }
        case "ENDCASE": close("CASE"); break;
        // PROCEDURE/FUNCTION never nest (the grammar only allows them at the
        // very top of the program -- see scanDefinitions), so whenever one of
        // these frames is present it is always the outermost, at stack[0].
        case "PROCEDURE": stack.push({ type: "PROCEDURE" }); break;
        case "ENDPROCEDURE": close("PROCEDURE"); break;
        case "FUNCTION": stack.push({ type: "FUNCTION" }); break;
        case "ENDFUNCTION": close("FUNCTION"); break;
        default: break;
      }
    }
    return { stack, pendingThen, pendingDo };
  }

  // Whether every top-level line up to here has itself been part of a
  // PROCEDURE/FUNCTION definition (or blank) -- i.e. a PROCEDURE/FUNCTION
  // keyword is still syntactically valid on the next line (SRS 3.10: "always
  // defined at the top of the program"). Whether we're CURRENTLY inside an
  // open definition (and which kind) is instead read directly off
  // analyzeBlocks' stack (blocks.stack[0]) wherever that's needed, since a
  // PROCEDURE/FUNCTION frame never nests and so is always the outermost one.
  function atTopOfProgram(before) {
    let atTop = true;
    let openKind = null;
    let atLineStart = true;
    for (let i = 0; i < before.length; i += 1) {
      const tk = before[i];
      if (tk.t === "nl") { atLineStart = true; continue; }
      if (!atLineStart) continue;
      atLineStart = false;
      if (openKind) {
        const closes = openKind === "PROCEDURE" ? "ENDPROCEDURE" : "ENDFUNCTION";
        if (tk.t === "kw" && tk.v === closes) openKind = null;
        continue;
      }
      if (tk.t === "kw" && (tk.v === "PROCEDURE" || tk.v === "FUNCTION")) { openKind = tk.v; continue; }
      atTop = false;
    }
    return atTop && !openKind;
  }

  // name -> {name, kind: "procedure" | "function", params: [{name, type, isArray}], returnType}
  // A best-effort forward scan mirroring collectSymbols: partial/unfinished
  // definitions (including the one currently being typed) simply end up with
  // fewer/blank fields rather than being excluded, since that only makes a
  // suggestion slightly less specific, never wrong.
  function collectRoutines(toks) {
    const routines = new Map();
    for (let i = 0; i < toks.length; i += 1) {
      const tk = toks[i];
      if (!(tk.t === "kw" && (tk.v === "PROCEDURE" || tk.v === "FUNCTION"))) continue;
      const isFunction = tk.v === "FUNCTION";
      const nameTok = toks[i + 1];
      if (!(nameTok && nameTok.t === "id")) continue;
      const { params, next } = parseParamClause(toks, i + 2);
      let returnType = null;
      if (
        isFunction && toks[next] && toks[next].t === "kw" && toks[next].v === "RETURNS" &&
        toks[next + 1] && toks[next + 1].t === "kw" && TYPES.includes(toks[next + 1].v)
      ) {
        returnType = toks[next + 1].v;
      }
      routines.set(nameTok.v, { name: nameTok.v, kind: isFunction ? "function" : "procedure", params, returnType });
    }
    return routines;
  }

  // ---- current statement -------------------------------------------------
  function isCaseValue(toks) {
    if (toks.length === 1) return toks[0].t === "lit";
    return toks.length === 2 && toks[0].t === "op" && toks[0].v === "-" && toks[1].t === "lit";
  }

  // The part of the current line that belongs to the statement being typed:
  // anything after THEN / ELSE / DO / OTHERWISE / REPEAT, or after the colon of
  // a CASE branch ("'a' : ..."), starts a fresh statement.
  function currentStatement(line) {
    let start = 0;
    for (let i = 0; i < line.length; i += 1) {
      const tk = line[i];
      if (tk.t === "kw" && STATEMENT_STARTERS.has(tk.v)) start = i + 1;
      else if (tk.t === ":" && isCaseValue(line.slice(start, i))) start = i + 1;
    }
    return line.slice(start);
  }

  // ---- candidate factories -----------------------------------------------
  // group controls ordering: 0 expected keyword / closer, 1 keyword,
  // 2 variable, 3 function, 4 literal, 9 not supported yet.
  function keyword(label, group, strong) {
    const info = meta.get(label) || {};
    const notYet = NOT_YET.has(label);
    return {
      label,
      kind: info.kind || "keyword",
      detail: notYet ? "Not supported yet" : info.detail,
      group: notYet ? "9" : group,
      // "strong": the grammar requires exactly this here, so it is safe to
      // offer even after a single typed letter.
      strong: Boolean(strong),
    };
  }

  function symbolCandidate(sym) {
    let detail;
    if (sym.kind === "array") detail = `ARRAY[${sym.bounds}] OF ${sym.type}`;
    else if (sym.kind === "const") detail = sym.type ? `CONSTANT (${sym.type})` : "CONSTANT";
    else detail = `${sym.type} variable`;
    return {
      label: sym.name,
      kind: sym.kind === "const" ? "constant" : "variable",
      detail,
      group: "2",
      strong: true,
    };
  }

  function routineCandidate(r) {
    const paramList = r.params
      .map((p) => `${p.name}:${p.isArray ? `ARRAY OF ${p.type || "?"}` : (p.type || "?")}`)
      .join(", ");
    const detail = r.kind === "function"
      ? `FUNCTION(${paramList}) RETURNS ${r.returnType || "?"}`
      : `PROCEDURE(${paramList})`;
    return { label: r.name, kind: "function", detail, group: "2", strong: true };
  }

  const typeCandidates = (withArray) =>
    [...TYPES, ...(withArray ? ["ARRAY"] : [])].map((label) => keyword(label, "0", true));

  const fits = (sym, type) => {
    const cat = CATEGORY[sym.type];
    return type === "any" || !cat || cat === type;
  };

  function operandCandidates(type, symbols) {
    const out = [];
    for (const sym of symbols.values()) if (fits(sym, type)) out.push(symbolCandidate(sym));
    for (const fn of lang.builtinFunctions) {
      if (type === "any" || RETURNS[fn] === type) out.push(keyword(fn, "3", false));
    }
    if (type === "any") out.push(keyword("TRUE", "4"), keyword("FALSE", "4"), keyword("NOT", "1"));
    return out;
  }

  // ---- expressions -------------------------------------------------------
  // Walk the tokens of an expression, tracking (), built-in call arguments and
  // [] indices, to decide whether an operand or an operator/keyword comes
  // next and what type the operand must have.
  function scanExpression(slice, baseType) {
    const frames = [];
    for (let i = 0; i < slice.length; i += 1) {
      const tk = slice[i];
      if (tk.t === "(") {
        const p = slice[i - 1];
        const isCall = p && p.t === "id" && BUILTINS.has(p.v);
        frames.push({ kind: isCall ? "call" : "group", name: isCall ? p.v : null, arg: 0 });
      } else if (tk.t === "[") {
        frames.push({ kind: "index", arg: 0 });
      } else if (tk.t === "," && frames.length) {
        frames[frames.length - 1].arg += 1;
      } else if ((tk.t === ")" || tk.t === "]") && frames.length) {
        frames.pop();
      }
    }
    let type = baseType;
    for (let k = frames.length - 1; k >= 0; k -= 1) {
      const f = frames[k];
      if (f.kind === "index") { type = "numeric"; break; }
      if (f.kind === "call") { type = (ARGUMENTS[f.name] || [])[f.arg] || "any"; break; }
    }
    const last = slice[slice.length - 1];
    const operandEnded = Boolean(last) && (last.t === "lit" || last.t === "id" || last.t === ")" || last.t === "]");
    return { expectOperand: !operandEnded, type, depth: frames.length };
  }

  // opts.then: keywords that may follow a finished expression at top level
  // opts.logic: whether AND / OR make sense here
  function expression(slice, baseType, opts, symbols) {
    const last = slice[slice.length - 1];
    if (last && last.t === "id" && BUILTINS.has(last.v)) return []; // "(" comes next
    const state = scanExpression(slice, baseType);
    if (state.expectOperand) return operandCandidates(state.type, symbols);
    const out = [];
    if (state.depth === 0) for (const word of opts.then || []) out.push(keyword(word, "0", true));
    if (opts.logic && state.type === "any") out.push(keyword("AND", "1"), keyword("OR", "1"));
    return out;
  }

  // ---- per-statement contexts ---------------------------------------------
  function startOfStatement(lineStart, blocks, symbols, atTop) {
    const out = [];
    if (lineStart) {
      // "THEN" and "DO" may sit on the line after their IF / WHILE header.
      if (blocks.pendingThen) return [keyword("THEN", "0", true)];
      if (blocks.pendingDo) return [keyword("DO", "0", true)];
      const top = blocks.stack[blocks.stack.length - 1];
      if (top && top.type === "CASE") {
        // Inside CASE OF, a line is a branch value, OTHERWISE or ENDCASE.
        if (!top.hasOtherwise) out.push(keyword("OTHERWISE", "0"));
        out.push(keyword("ENDCASE", "0"));
        const subject = top.subject && symbols.get(top.subject);
        if (subject && subject.type === "BOOLEAN") out.push(keyword("TRUE", "4"), keyword("FALSE", "4"));
        return out;
      }
      // Only the innermost open block can be closed next.
      if (top && top.type === "IF") {
        if (!top.hasElse) out.push(keyword("ELSE", "0"));
        out.push(keyword("ENDIF", "0"));
      } else if (top && top.type === "FOR") out.push(keyword("NEXT", "0"));
      else if (top && top.type === "WHILE") out.push(keyword("ENDWHILE", "0"));
      else if (top && top.type === "REPEAT") out.push(keyword("UNTIL", "0"));
      else if (top && top.type === "PROCEDURE") out.push(keyword("ENDPROCEDURE", "0"));
      else if (top && top.type === "FUNCTION") out.push(keyword("ENDFUNCTION", "0"));
      // PROCEDURE/FUNCTION (FR-10.1, FR-10.3) are only valid here, at the
      // very top of the program, with no other block currently open.
      if (atTop && blocks.stack.length === 0) {
        out.push(keyword("PROCEDURE", "1"), keyword("FUNCTION", "1"));
      }
      // RETURN (FR-10.3) is only valid inside a FUNCTION body, never a
      // PROCEDURE body or the main program. A PROCEDURE/FUNCTION frame never
      // nests, so it's always stack[0] when one is open at all.
      if (blocks.stack[0] && blocks.stack[0].type === "FUNCTION") out.push(keyword("RETURN", "1"));
    }
    for (const word of STATEMENT_KEYWORDS) out.push(keyword(word, "1"));
    for (const word of NOT_YET) out.push(keyword(word, "9"));
    for (const sym of symbols.values()) if (sym.kind !== "const") out.push(symbolCandidate(sym));
    return out;
  }

  function declareContext(stmt, symbols) {
    const colon = stmt.findIndex((tk) => tk.t === ":");
    if (colon < 0) return []; // naming a new variable: nothing to suggest
    const after = stmt.slice(colon + 1);
    if (after.length === 0) return typeCandidates(true);
    if (after[0].t === "kw" && after[0].v === "ARRAY") {
      const of = after.findIndex((tk) => tk.t === "kw" && tk.v === "OF");
      if (of >= 0) return of === after.length - 1 ? typeCandidates(false) : [];
      if (after.length === 1 || after[1].t !== "[") return [];
      let depth = 0;
      for (const tk of after) {
        if (tk.t === "[") depth += 1;
        else if (tk.t === "]") depth -= 1;
      }
      if (depth > 0) return expression(after.slice(1), "numeric", {}, symbols); // inside the bounds
      return [keyword("OF", "0", true)];
    }
    return [];
  }

  function forContext(stmt, symbols) {
    if (stmt.length === 1) {
      return [...symbols.values()]
        .filter((s) => s.kind === "var" && CATEGORY[s.type] === "numeric")
        .map(symbolCandidate);
    }
    const assign = stmt.findIndex((tk) => tk.t === "assign");
    if (assign < 0) return []; // "<-" comes next
    const to = stmt.findIndex((tk, k) => k > assign && tk.t === "kw" && tk.v === "TO");
    if (to < 0) return expression(stmt.slice(assign + 1), "numeric", { then: ["TO"] }, symbols);
    const step = stmt.findIndex((tk, k) => k > to && tk.t === "kw" && tk.v === "STEP");
    if (step < 0) return expression(stmt.slice(to + 1), "numeric", { then: ["STEP"] }, symbols);
    return expression(stmt.slice(step + 1), "numeric", {}, symbols);
  }

  // A PROCEDURE/FUNCTION header line, from the keyword itself up to (and
  // including) RETURNS <type> for a FUNCTION: <id> ( <id> : <type>, ...)
  // [RETURNS <type>]. A parameter's type may itself be ARRAY[...] OF <type>
  // (an extension beyond the SRS's literal grammar, added on request) --
  // that clause is handled exactly like declareContext handles a DECLARE's
  // array type, just scoped to the CURRENT parameter's own clause (a header
  // can have several parameters, each with its own colon and, potentially,
  // its own array brackets), plus RETURNS for a FUNCTION.
  function routineHeaderContext(stmt, isFunction, symbols) {
    const lparen = stmt.findIndex((tk) => tk.t === "(");
    if (lparen < 0) {
      // No '(' yet: either about to type one, or (a FUNCTION with no
      // parameters) RETURNS follows the name directly.
      return stmt.length === 2 && stmt[1].t === "id" && isFunction ? [keyword("RETURNS", "0", true)] : [];
    }
    const rest = stmt.slice(lparen + 1);
    let depth = 1;
    let closeIndex = -1;
    for (let k = 0; k < rest.length; k += 1) {
      if (rest[k].t === "(" || rest[k].t === "[") depth += 1;
      else if (rest[k].t === ")" || rest[k].t === "]") {
        depth -= 1;
        if (depth === 0) { closeIndex = k; break; }
      }
    }
    if (closeIndex >= 0) {
      // The parameter list has already been closed (possibly empty, "()").
      const afterClose = rest.slice(closeIndex + 1);
      if (afterClose.length === 0) return isFunction ? [keyword("RETURNS", "0", true)] : [];
      const last = afterClose[afterClose.length - 1];
      if (isFunction && last && last.t === "kw" && last.v === "RETURNS") return typeCandidates(false);
      return [];
    }
    // Still inside the (unclosed) parameter list: find where the CURRENT
    // parameter's own clause starts -- right after the last top-level comma
    // (or the very start, for the first parameter).
    let clauseStart = 0;
    let d = 0;
    for (let k = 0; k < rest.length; k += 1) {
      const tk = rest[k];
      if (tk.t === "(" || tk.t === "[") d += 1;
      else if (tk.t === ")" || tk.t === "]") d -= 1;
      else if (tk.t === "," && d === 0) clauseStart = k + 1;
    }
    const clause = rest.slice(clauseStart);
    const colon = clause.findIndex((tk) => tk.t === ":");
    if (colon < 0) return []; // naming the parameter itself: nothing to suggest
    const after = clause.slice(colon + 1);
    if (after.length === 0) return typeCandidates(true);
    if (after[0].t === "kw" && after[0].v === "ARRAY") {
      const of = after.findIndex((tk) => tk.t === "kw" && tk.v === "OF");
      if (of >= 0) return of === after.length - 1 ? typeCandidates(false) : [];
      if (after.length === 1 || after[1].t !== "[") return [];
      let bd = 0;
      for (const tk of after) {
        if (tk.t === "[") bd += 1;
        else if (tk.t === "]") bd -= 1;
      }
      if (bd > 0) return expression(after.slice(1), "numeric", {}, symbols); // inside the bounds
      return [keyword("OF", "0", true)];
    }
    return []; // typing the data type itself: nothing further to suggest
  }

  // CALL <identifier> [(<args>)]   (FR-10.2). Only PROCEDUREs are offered as
  // the name, never FUNCTIONs (FR-10.4: CALLing one is a compiler error), and
  // once inside the parens, each argument is matched to that PROCEDURE's
  // declared parameter type exactly like a built-in call's arguments are.
  function callContext(stmt, routines, symbols) {
    if (stmt.length === 1) {
      const out = [];
      for (const r of routines.values()) if (r.kind === "procedure") out.push(routineCandidate(r));
      return out;
    }
    const nameTok = stmt[1];
    if (!(nameTok && nameTok.t === "id")) return [];
    if (!(stmt[2] && stmt[2].t === "(")) return []; // no parens (yet): nothing more to suggest
    const inner = stmt.slice(3);
    let depth = 0;
    let argIndex = 0;
    let sliceStart = 0;
    for (let k = 0; k < inner.length; k += 1) {
      const tk = inner[k];
      if (tk.t === "(" || tk.t === "[") depth += 1;
      else if (tk.t === ")" || tk.t === "]") depth -= 1;
      else if (tk.t === "," && depth === 0) { argIndex += 1; sliceStart = k + 1; }
    }
    const routine = routines.get(nameTok.v);
    const param = routine && routine.params[argIndex];
    if (param && param.isArray) {
      // An array argument must be a plain array name of matching element
      // type (FR-10.2 extension -- see Interpreter._bind_array_argument);
      // the shared expression machinery is expression-oriented and doesn't
      // fit here, so array names are suggested directly instead.
      const out = [];
      for (const sym of symbols.values()) if (sym.kind === "array" && sym.type === param.type) out.push(symbolCandidate(sym));
      return out;
    }
    const argType = param && param.type ? (CATEGORY[param.type] || "any") : "any";
    return expression(inner.slice(sliceStart), argType, {}, symbols);
  }

  function statementContext(stmt, blocks, symbols, routines) {
    const first = stmt[0];
    if (first.t === "id") {
      const assign = stmt.findIndex((tk) => tk.t === "assign");
      if (assign >= 0) return expression(stmt.slice(assign + 1), "any", { logic: true }, symbols);
      if (stmt[1] && stmt[1].t === "[") return expression(stmt.slice(1), "numeric", {}, symbols);
      return []; // "<-" comes next
    }
    if (first.t !== "kw") return [];
    const rest = stmt.slice(1);
    switch (first.v) {
      case "DECLARE": return declareContext(stmt, symbols);
      case "CONSTANT": {
        const assign = stmt.findIndex((tk) => tk.t === "assign");
        return assign >= 0 ? expression(stmt.slice(assign + 1), "any", {}, symbols) : [];
      }
      case "INPUT": {
        if (stmt.length === 1) {
          return [...symbols.values()].filter((s) => s.kind !== "const").map(symbolCandidate);
        }
        return stmt[2] && stmt[2].t === "[" ? expression(stmt.slice(2), "numeric", {}, symbols) : [];
      }
      case "OUTPUT": return expression(rest, "any", { logic: true }, symbols);
      case "IF": return expression(rest, "any", { then: ["THEN"], logic: true }, symbols);
      case "WHILE": return expression(rest, "any", { then: ["DO"], logic: true }, symbols);
      case "UNTIL": return expression(rest, "any", { logic: true }, symbols);
      case "FOR": return forContext(stmt, symbols);
      case "CASE": {
        if (stmt.length === 1) return [keyword("OF", "0", true)];
        if (stmt.length === 2 && stmt[1].t === "kw" && stmt[1].v === "OF") {
          return [...symbols.values()].filter((s) => s.kind !== "array").map(symbolCandidate);
        }
        return [];
      }
      case "NEXT": {
        if (stmt.length > 1) return [];
        for (let k = blocks.stack.length - 1; k >= 0; k -= 1) {
          if (blocks.stack[k].type === "FOR") {
            const name = blocks.stack[k].variable;
            const sym = name && symbols.get(name);
            return sym ? [symbolCandidate(sym)] : [];
          }
        }
        return [];
      }
      case "PROCEDURE": return routineHeaderContext(stmt, false, symbols);
      case "FUNCTION": return routineHeaderContext(stmt, true, symbols);
      case "CALL": return callContext(stmt, routines, symbols);
      case "RETURN": return expression(rest, "any", { logic: true }, symbols);
      default: return [];
    }
  }

  // ---- public ------------------------------------------------------------
  function candidates(textBeforeWord) {
    const toks = tokenize(textBeforeWord);
    let lastNewline = -1;
    for (let k = toks.length - 1; k >= 0; k -= 1) {
      if (toks[k].t === "nl") { lastNewline = k; break; }
    }
    const before = toks.slice(0, lastNewline + 1);
    const line = toks.slice(lastNewline + 1);
    const symbols = collectSymbols(toks);
    const routines = collectRoutines(toks);
    const blocks = analyzeBlocks(before);
    const stmt = currentStatement(line);
    if (stmt.length === 0) return startOfStatement(line.length === 0, blocks, symbols, atTopOfProgram(before));
    return statementContext(stmt, blocks, symbols, routines);
  }

  return { candidates, tokenize };
}

window.PseudocodeMonaco = Object.freeze({
  languageId: "igcse-pseudocode",
  aliases: ["IGCSE Pseudocode", "Pseudocode"],
  extensions: [".pseudo", ".pseudocode"],

  configuration: {
    comments: {
      lineComment: "//",
    },

    brackets: [
      ["(", ")"],
      ["[", "]"],
    ],

    autoClosingPairs: [
      { open: "(", close: ")" },
      { open: "[", close: "]" },
      { open: '"', close: '"' },
      { open: "'", close: "'" },
    ],

    surroundingPairs: [
      ["(", ")"],
      ["[", "]"],
      ['"', '"'],
      ["'", "'"],
    ],

    wordPattern: /[A-Za-z_][A-Za-z0-9_]*/,

    // Keep the editor at the same four-space indentation convention as the
    // existing textarea editor. Block keywords are deliberately based on
    // the pseudocode grammar rather than on braces, because pseudocode uses
    // named terminators (ENDIF, NEXT, ENDWHILE, ...).
    // Indentation. A block header indents the lines after it whether or not it
    // is complete yet: "WHILE NOT done" (DO still to be typed, or on the next
    // line), "IF x = 1" (THEN on the next line, as in the SRS's own example) and
    // headers followed by a trailing "// comment" all open a block, exactly like
    // "WHILE NOT done DO" does.
    //
    // THEN may also sit alone on the line after its IF header. Like ELSE, such a
    // line lines up with the header (decrease) and indents its body (increase),
    // giving the layout shown in SRS section 3.7.1:
    //
    //     IF Answer = CorrectAnswer
    //     THEN
    //         Score <- Score + 1
    //     ELSE
    //         OUTPUT "Wrong Answer!"
    //     ENDIF
    //
    // DO is deliberately NOT treated the same way: a lone-DO rule would outdent
    // any line that merely starts with an uppercase word such as DONE or DOUBLE,
    // because typing "DO" momentarily matches it. WHILE cond / DO on the next
    // line is still valid; DO simply stays at the body's indentation.
    indentationRules: {
      increaseIndentPattern:
        /^\s*(?:IF\b.*|FOR\b.*|WHILE\b.*|REPEAT\b.*|CASE\s+OF\b.*|PROCEDURE\b.*|FUNCTION\b.*|ELSE\b.*|THEN\s*(?:\/\/.*)?)$/,
      decreaseIndentPattern:
        /^\s*(?:(?:ENDIF|NEXT|UNTIL|ENDWHILE|ENDCASE|ENDPROCEDURE|ENDFUNCTION|ELSE)\b.*|THEN\s*(?:\/\/.*)?)$/,
    },

    // onEnterRules refine the block behavior for lines where entering a new
    // line should add a level, or where a closing keyword should move the
    // cursor back to the surrounding block level. (ELSE and THEN are handled by
    // indentationRules above; adding them here would indent twice.)
    onEnterRules: [
      {
        beforeText: /^\s*(?:IF\b.*|FOR\b.*|REPEAT\b.*|WHILE\b.*|CASE\s+OF\b.*|PROCEDURE\b.*|FUNCTION\b.*)$/,
        action: { indentAction: 1 }, // Indent
      },
      {
        beforeText: /^\s*(?:ENDIF\b|NEXT\b|UNTIL\b|ENDWHILE\b|ENDCASE\b|ENDPROCEDURE\b|ENDFUNCTION\b).*$/,
        action: { indentAction: 0 }, // None; indentationRules performs the outdent
      },
    ],
  },

  language: {
    defaultToken: "",
    controlKeywords: [
      "IF", "THEN", "ELSE", "ENDIF",
      "CASE", "OF", "OTHERWISE", "ENDCASE",
      "FOR", "TO", "STEP", "NEXT",
      "REPEAT", "UNTIL", "WHILE", "DO", "ENDWHILE",
    ],
    declarationKeywords: ["DECLARE", "CONSTANT"],
    ioKeywords: ["INPUT", "OUTPUT"],
    arrayKeywords: ["ARRAY"],
    typeKeywords: ["INTEGER", "REAL", "CHAR", "STRING", "BOOLEAN"],
    fileKeywords: ["OPENFILE", "READFILE", "WRITEFILE", "CLOSEFILE", "READ", "WRITE"],
    routineKeywords: ["PROCEDURE", "ENDPROCEDURE", "FUNCTION", "RETURNS", "ENDFUNCTION", "CALL", "RETURN"],
    logicalKeywords: ["AND", "OR", "NOT"],
    booleanLiterals: ["TRUE", "FALSE"],
    builtinFunctions: ["ROUND", "RANDOM", "DIV", "MOD", "LENGTH", "LCASE", "UCASE", "SUBSTRING"],

    tokenizer: {
      root: [
        // Comments must be checked before the division operator.
        [/\/\/.*$/, "comment"],

        // String and CHAR literals. The compiler itself does not implement
        // escape sequences, so highlighting intentionally stays permissive
        // and visual rather than trying to validate literal contents.
        [/'[^'\r\n]*'/, "string"],
        [/"[^"\r\n]*"/, "string"],

        // Numeric literals.
        [/\b\d+\.\d+\b/, "number"],
        [/\b\d+\b/, "number"],

        // Assignment arrow first so "<-" is not split into two operators.
        [/<-|←|<>|<=|>=|[+\-*\/%^=<>]/, "operator"],

        // Pseudocode punctuation.
        [/[()[\]{},:]/, "delimiter"],

        // Keywords, types, literals, and built-ins are distinguished so the
        // theme can present a useful visual hierarchy.
        [/[A-Za-z_][A-Za-z0-9_]*/, {
          cases: {
            "@typeKeywords": "type",
            "@controlKeywords": "keyword.control",
            "@declarationKeywords": "keyword.declaration",
            "@ioKeywords": "keyword.io",
            "@arrayKeywords": "keyword.array",
            "@fileKeywords": "keyword.file",
            "@routineKeywords": "keyword.routine",
            "@logicalKeywords": "keyword.operator",
            "@booleanLiterals": "constant.language",
            "@builtinFunctions": "predefined",
            "@default": "identifier",
          },
        }],

        // Keep whitespace explicit so Monarch does not inherit surprises from
        // a generic language definition.
        [/\s+/, "white"],
      ],
    },
  },



  // The language vocabulary and its display metadata (kind + detail). This
  // table does not decide WHEN an entry is offered: that is the job of
  // buildCompletionEngine, which reads the surrounding code and picks from
  // this vocabulary plus the variables the program has declared.
  completions: [
    { label: "IF", kind: "keyword", detail: "Selection keyword" },
    { label: "THEN", kind: "keyword", detail: "Selection keyword" },
    { label: "ELSE", kind: "keyword", detail: "Selection keyword" },
    { label: "ENDIF", kind: "keyword", detail: "Selection keyword" },
    { label: "CASE", kind: "keyword", detail: "Selection keyword" },
    { label: "OF", kind: "keyword", detail: "Selection keyword" },
    { label: "OTHERWISE", kind: "keyword", detail: "Selection keyword" },
    { label: "ENDCASE", kind: "keyword", detail: "Selection keyword" },
    { label: "FOR", kind: "keyword", detail: "Iteration keyword" },
    { label: "TO", kind: "keyword", detail: "Iteration keyword" },
    { label: "STEP", kind: "keyword", detail: "Iteration keyword" },
    { label: "NEXT", kind: "keyword", detail: "Iteration keyword" },
    { label: "REPEAT", kind: "keyword", detail: "Iteration keyword" },
    { label: "UNTIL", kind: "keyword", detail: "Iteration keyword" },
    { label: "WHILE", kind: "keyword", detail: "Iteration keyword" },
    { label: "DO", kind: "keyword", detail: "Iteration keyword" },
    { label: "ENDWHILE", kind: "keyword", detail: "Iteration keyword" },
    { label: "DECLARE", kind: "keyword", detail: "Declaration keyword" },
    { label: "CONSTANT", kind: "keyword", detail: "Declaration keyword" },
    { label: "INPUT", kind: "keyword", detail: "Input keyword" },
    { label: "OUTPUT", kind: "keyword", detail: "Output keyword" },
    { label: "ARRAY", kind: "keyword", detail: "Array keyword" },
    { label: "PROCEDURE", kind: "keyword", detail: "Procedure keyword" },
    { label: "ENDPROCEDURE", kind: "keyword", detail: "Procedure keyword" },
    { label: "FUNCTION", kind: "keyword", detail: "Function keyword" },
    { label: "RETURNS", kind: "keyword", detail: "Function keyword" },
    { label: "ENDFUNCTION", kind: "keyword", detail: "Function keyword" },
    { label: "CALL", kind: "keyword", detail: "Procedure/function keyword" },
    { label: "RETURN", kind: "keyword", detail: "Function keyword" },
    { label: "OPENFILE", kind: "keyword", detail: "File-handling keyword" },
    { label: "READFILE", kind: "keyword", detail: "File-handling keyword" },
    { label: "WRITEFILE", kind: "keyword", detail: "File-handling keyword" },
    { label: "CLOSEFILE", kind: "keyword", detail: "File-handling keyword" },
    { label: "READ", kind: "keyword", detail: "File mode" },
    { label: "WRITE", kind: "keyword", detail: "File mode" },
    { label: "INTEGER", kind: "type", detail: "Data type" },
    { label: "REAL", kind: "type", detail: "Data type" },
    { label: "CHAR", kind: "type", detail: "Data type" },
    { label: "STRING", kind: "type", detail: "Data type" },
    { label: "BOOLEAN", kind: "type", detail: "Data type" },
    { label: "TRUE", kind: "value", detail: "Boolean literal" },
    { label: "FALSE", kind: "value", detail: "Boolean literal" },
    { label: "AND", kind: "operator", detail: "Logical operator" },
    { label: "OR", kind: "operator", detail: "Logical operator" },
    { label: "NOT", kind: "operator", detail: "Logical operator" },
    { label: "ROUND", kind: "function", detail: "Built-in function" },
    { label: "RANDOM", kind: "function", detail: "Built-in function" },
    { label: "DIV", kind: "function", detail: "Built-in function" },
    { label: "MOD", kind: "function", detail: "Built-in function" },
    { label: "LENGTH", kind: "function", detail: "Built-in function" },
    { label: "LCASE", kind: "function", detail: "Built-in function" },
    { label: "UCASE", kind: "function", detail: "Built-in function" },
    { label: "SUBSTRING", kind: "function", detail: "Built-in function" },
  ],

  registerCompletionProvider(monaco) {
    const kindMap = {
      keyword: monaco.languages.CompletionItemKind.Keyword,
      type: monaco.languages.CompletionItemKind.TypeParameter,
      value: monaco.languages.CompletionItemKind.Value,
      operator: monaco.languages.CompletionItemKind.Operator,
      function: monaco.languages.CompletionItemKind.Function,
      variable: monaco.languages.CompletionItemKind.Variable,
      constant: monaco.languages.CompletionItemKind.Constant,
    };
    const engine = buildCompletionEngine(this.language, this.completions);

    return monaco.languages.registerCompletionItemProvider(this.languageId, {
      provideCompletionItems(model, position) {
        const line = model.getLineContent(position.lineNumber).slice(0, position.column - 1);

        // Stay quiet inside comments and string/CHAR literals, where neither
        // keywords nor variable names are ever valid.
        let inString = null;
        for (let i = 0; i < line.length; i += 1) {
          const ch = line[i];
          if (inString) {
            if (ch === inString) inString = null;
          } else if (ch === '"' || ch === "'") {
            inString = ch;
          } else if (ch === "/" && line[i + 1] === "/") {
            return { suggestions: [] };
          }
        }
        if (inString) return { suggestions: [] };

        // Everything before the word being typed decides what is expected.
        const word = model.getWordUntilPosition(position);
        const textBeforeWord = model.getValueInRange({
          startLineNumber: 1,
          startColumn: 1,
          endLineNumber: position.lineNumber,
          endColumn: word.startColumn,
        });
        let candidates = engine.candidates(textBeforeWord);

        // Prefix-only matching. Monaco's own filter is fuzzy (subsequence), so
        // the identifier "Cnt" would otherwise match CONSTANT.
        const prefix = word.word.toUpperCase();
        candidates = candidates.filter((c) => c.label.toUpperCase().startsWith(prefix));

        // After a single letter, only offer names the program itself declared
        // and keywords the grammar requires at this exact spot (THEN, TO, a data
        // type ...). Open-ended keyword lists would let Enter rewrite a
        // one-letter variable such as i or n into IF or NEXT.
        if (word.word.length === 1) candidates = candidates.filter((c) => c.strong);

        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };
        return {
          suggestions: candidates.map((c) => ({
            label: c.label,
            kind: kindMap[c.kind] ?? monaco.languages.CompletionItemKind.Text,
            detail: c.detail,
            insertText: c.label,
            sortText: c.group + c.label,
            range,
          })),
          incomplete: true, // re-query on every keystroke so context and prefix stay current
        };
      },
    });
  },

  theme: {
    name: "igcse-pseudocode-dark",
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "6A9955" },
      { token: "string", foreground: "CE9178" },
      { token: "number", foreground: "B5CEA8" },
      { token: "type", foreground: "4EC9B0" },
      { token: "keyword.control", foreground: "C586C0" },
      { token: "keyword.declaration", foreground: "569CD6" },
      { token: "keyword.io", foreground: "569CD6" },
      { token: "keyword.array", foreground: "569CD6" },
      { token: "keyword.file", foreground: "569CD6" },
      { token: "keyword.routine", foreground: "569CD6" },
      { token: "keyword.operator", foreground: "DCDCAA" },
      { token: "constant.language", foreground: "569CD6" },
      { token: "predefined", foreground: "DCDCAA" },
      { token: "operator", foreground: "D4D4D4" },
      { token: "delimiter", foreground: "D4D4D4" },
      { token: "identifier", foreground: "D4D4D4" },
    ],
    colors: {
      "editor.background": "#1b1d24",
      "editor.foreground": "#e7e8ee",
      "editorGutter.background": "#1b1d24",
      "editorLineNumber.foreground": "#4a4d5a",
      "editorLineNumber.activeForeground": "#8b8fa0",
      "editorCursor.foreground": "#f2a541",
      "editor.selectionBackground": "#353945",
      "editor.inactiveSelectionBackground": "#2a2d38",
    },
  },
});
