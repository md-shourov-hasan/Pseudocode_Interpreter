/*
 * Monaco language definition for Cambridge/IGCSE-style pseudocode.
 *
 * This file contains editor-facing language intelligence only: syntax
 * colorization, keyword classification, bracket behavior, and indentation.
 * The compiler's Python lexer/parser remain the source of truth for actual
 * language validation and execution.
 *
 * Monaco Editor 0.56.0 is loaded by index.html. The AMD loader is used here
 * because the current Flask application does not have a frontend bundler yet.
 * Monaco has deprecated AMD in favor of ESM, so this is intentionally kept as
 * a migration-friendly adapter rather than being coupled to application code.
 */

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



  // Level 1 completion is intentionally static. It provides the fixed
  // vocabulary of the pseudocode language without attempting to inspect the
  // current document, symbol table, or AST. Context-aware completion belongs
  // to a later language-service milestone.
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
    };

    const suggestions = this.completions.map((item) => ({
      label: item.label,
      kind: kindMap[item.kind] ?? monaco.languages.CompletionItemKind.Text,
      detail: item.detail,
      insertText: item.label,
      sortText: item.label,
    }));

    return monaco.languages.registerCompletionItemProvider(this.languageId, {
      provideCompletionItems(model, position) {
        const line = model.getLineContent(position.lineNumber).slice(0, position.column - 1);

        // Level 1 stays static, but should still stay quiet inside comments
        // and string/CHAR literals, where keywords are never valid.
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

        // Prefix-only matching. Monaco's own filter is fuzzy (subsequence), so
        // the identifier "Cnt" would otherwise match CONSTANT.
        const word = model.getWordUntilPosition(position);
        const prefix = word.word.toUpperCase();
        // Single-letter words are almost always loop counters or variables
        // (i, j, n, t ...). Offering IF/INPUT/NEXT/TO for them means Enter
        // would rewrite the variable, so suggest from two characters up.
        if (word.word.length === 1) return { suggestions: [], incomplete: true };
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: word.endColumn,
        };
        return {
          suggestions: suggestions
            .filter((s) => s.label.startsWith(prefix))
            .map((s) => ({ ...s, range })),
          incomplete: true, // re-query on every keystroke so the prefix filter stays current
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
