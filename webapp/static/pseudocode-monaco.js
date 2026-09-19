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
  // milestones 8 and 9). They are still offered, ranked last and labelled.
  const NOT_YET = new Set([
    "OPENFILE", "READFILE", "WRITEFILE", "CLOSEFILE", "CALL", "PROCEDURE", "FUNCTION",
  ]);
  const STATEMENT_KEYWORDS = [
    "DECLARE", "CONSTANT", "INPUT", "OUTPUT", "IF", "CASE", "FOR", "REPEAT", "WHILE",
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
  function collectSymbols(toks) {
    const symbols = new Map();
    for (let i = 0; i < toks.length; i += 1) {
      const tk = toks[i];
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
            for (const name of names) symbols.set(name, { name, kind: "array", type: type.v, bounds });
          }
        } else if (toks[j] && toks[j].t === "kw" && TYPES.includes(toks[j].v)) {
          for (const name of names) symbols.set(name, { name, kind: "var", type: toks[j].v });
        }
      } else if (tk.t === "kw" && tk.v === "CONSTANT") {
        const name = toks[i + 1];
        if (name && name.t === "id" && toks[i + 2] && toks[i + 2].t === "assign") {
          const value = toks[i + 3];
          symbols.set(name.v, {
            name: name.v, kind: "const", type: value && value.t === "lit" ? value.lit : null,
          });
        }
      }
    }
    return symbols;
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
        default: break;
      }
    }
    return { stack, pendingThen, pendingDo };
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
  function startOfStatement(lineStart, blocks, symbols) {
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

  function statementContext(stmt, blocks, symbols) {
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
    const blocks = analyzeBlocks(before);
    const stmt = currentStatement(line);
    if (stmt.length === 0) return startOfStatement(line.length === 0, blocks, symbols);
    return statementContext(stmt, blocks, symbols);
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
    indentationRules: {
      increaseIndentPattern:
        /^\s*(?:(?:IF\b.*\bTHEN\s*$)|(?:FOR\b.*$)|(?:REPEAT\s*$)|(?:WHILE\b.*\bDO\s*$)|(?:CASE\s+OF\b.*$)|(?:PROCEDURE\b.*$)|(?:FUNCTION\b.*$)|(?:ELSE\s*$))$/,
      decreaseIndentPattern:
        /^\s*(?:ENDIF\b|NEXT\b|UNTIL\b|ENDWHILE\b|ENDCASE\b|ENDPROCEDURE\b|ENDFUNCTION\b|ELSE\b).*$/,
    },

    // onEnterRules refine the block behavior for lines where entering a new
    // line should add a level, or where a closing keyword should move the
    // cursor back to the surrounding block level.
    onEnterRules: [
      {
        beforeText: /^\s*(?:IF\b.*\bTHEN|FOR\b.*|REPEAT\b|WHILE\b.*\bDO|CASE\s+OF\b.*|PROCEDURE\b.*|FUNCTION\b.*)\s*$/,
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