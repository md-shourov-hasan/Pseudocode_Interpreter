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
        /^\s*(?:(?:IF\b.*\bTHEN\s*$)|(?:FOR\b.*$)|(?:REPEAT\s*$)|(?:WHILE\b.*\bDO\s*$)|(?:CASE\s+OF\b.*$)|(?:PROCEDURE\b.*$)|(?:FUNCTION\b.*$))$/,
      decreaseIndentPattern:
        /^\s*(?:ENDIF\b|NEXT\b|UNTIL\b|ENDWHILE\b|ENDCASE\b|ENDPROCEDURE\b|ENDFUNCTION\b|ELSE\b|OTHERWISE\b).*$/,
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
        beforeText: /^\s*(?:ELSE\b|OTHERWISE\b).*$/,
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
