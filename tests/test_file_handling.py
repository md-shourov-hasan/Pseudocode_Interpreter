import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from engine.lexer import tokenize
from engine.parser import parse
from engine.interpreter import Interpreter
from engine.errors import PseudocodeError
from engine import ast_nodes as ast


def run_src(src: str, file_root, inputs=None):
    """Run pseudocode source with file access sandboxed to `file_root`
    (a pytest tmp_path) and return (output_lines, interpreter)."""
    program = parse(tokenize(src))
    queue = list(inputs or [])
    interp = Interpreter(
        input_fn=lambda: queue.pop(0) if queue else "",
        file_root=str(file_root),
    )
    output = interp.run(program)
    return output, interp


def parse_src(src: str):
    return parse(tokenize(src))


# ---- parsing (FR-9.1 - FR-9.4) ------------------------------------------


def test_openfile_parses():
    prog = parse_src('OPENFILE "Names.txt" FOR READ')
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.OpenFile)
    assert isinstance(stmt.file_expr, ast.Literal)
    assert stmt.file_expr.value == "Names.txt"
    assert stmt.mode == "READ"


def test_openfile_for_write_parses():
    prog = parse_src('OPENFILE "Out.txt" FOR WRITE')
    stmt = prog.statements[0]
    assert stmt.mode == "WRITE"


def test_openfile_rejects_bad_mode():
    with pytest.raises(PseudocodeError, match="READ or WRITE"):
        parse_src('OPENFILE "Names.txt" FOR APPEND')


def test_readfile_parses():
    prog = parse_src('READFILE "Names.txt", Data')
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.ReadFile)
    assert isinstance(stmt.target, ast.Identifier)
    assert stmt.target.name == "Data"


def test_writefile_parses():
    prog = parse_src('WRITEFILE "Remarks.txt", Remark')
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.WriteFile)
    assert isinstance(stmt.value, ast.Identifier)


def test_writefile_accepts_general_expression():
    prog = parse_src('WRITEFILE "Out.txt", "hello" + "!"')
    stmt = prog.statements[0]
    assert isinstance(stmt.value, ast.BinaryOp)


def test_closefile_parses():
    prog = parse_src('CLOSEFILE "Names.txt"')
    stmt = prog.statements[0]
    assert isinstance(stmt, ast.CloseFile)


def test_file_identifier_can_be_a_variable():
    prog = parse_src("OPENFILE Filename FOR READ")
    stmt = prog.statements[0]
    assert isinstance(stmt.file_expr, ast.Identifier)


# ---- end-to-end WRITE then READ round trip -------------------------------


def test_write_then_read_back_round_trip(tmp_path):
    src = """
    DECLARE Line1, Line2 : STRING
    OPENFILE "Out.txt" FOR WRITE
    WRITEFILE "Out.txt", "Hello"
    WRITEFILE "Out.txt", "World"
    CLOSEFILE "Out.txt"
    OPENFILE "Out.txt" FOR READ
    READFILE "Out.txt", Line1
    READFILE "Out.txt", Line2
    CLOSEFILE "Out.txt"
    OUTPUT Line1
    OUTPUT Line2
    """
    output, _ = run_src(src, tmp_path)
    assert output == ["Hello", "World"]


def test_writefile_creates_file_on_disk(tmp_path):
    src = 'OPENFILE "Data.txt" FOR WRITE\nWRITEFILE "Data.txt", "abc"\nCLOSEFILE "Data.txt"'
    run_src(src, tmp_path)
    written = (tmp_path / "Data.txt").read_text(encoding="utf-8")
    assert written == "abc\n"


def test_writefile_overwrites_existing_file(tmp_path):
    (tmp_path / "Data.txt").write_text("old content\nmore old content\n", encoding="utf-8")
    src = 'OPENFILE "Data.txt" FOR WRITE\nWRITEFILE "Data.txt", "new"\nCLOSEFILE "Data.txt"'
    run_src(src, tmp_path)
    written = (tmp_path / "Data.txt").read_text(encoding="utf-8")
    assert written == "new\n"


def test_readfile_coerces_types(tmp_path):
    (tmp_path / "Nums.txt").write_text("42\n3.5\nTRUE\nZ\n", encoding="utf-8")
    src = """
    DECLARE I : INTEGER
    DECLARE R : REAL
    DECLARE B : BOOLEAN
    DECLARE C : CHAR
    OPENFILE "Nums.txt" FOR READ
    READFILE "Nums.txt", I
    READFILE "Nums.txt", R
    READFILE "Nums.txt", B
    READFILE "Nums.txt", C
    CLOSEFILE "Nums.txt"
    OUTPUT I
    OUTPUT R
    OUTPUT B
    OUTPUT C
    """
    output, interp = run_src(src, tmp_path)
    assert interp.symbols["I"].value == 42
    assert interp.symbols["R"].value == 3.5
    assert interp.symbols["B"].value is True
    assert interp.symbols["C"].value == "Z"
    assert output == ["42", "3.5", "TRUE", "Z"]


def test_readfile_bad_value_for_type_is_error(tmp_path):
    (tmp_path / "Nums.txt").write_text("not-a-number\n", encoding="utf-8")
    src = 'DECLARE X : INTEGER\nOPENFILE "Nums.txt" FOR READ\nREADFILE "Nums.txt", X'
    with pytest.raises(PseudocodeError, match="Couldn't read"):
        run_src(src, tmp_path)


def test_readfile_into_undeclared_identifier_is_error(tmp_path):
    (tmp_path / "Nums.txt").write_text("1\n", encoding="utf-8")
    src = 'OPENFILE "Nums.txt" FOR READ\nREADFILE "Nums.txt", X'
    with pytest.raises(PseudocodeError, match="never declared"):
        run_src(src, tmp_path)


def test_readfile_into_constant_is_error(tmp_path):
    (tmp_path / "Nums.txt").write_text("1\n", encoding="utf-8")
    src = 'CONSTANT X <- 5\nOPENFILE "Nums.txt" FOR READ\nREADFILE "Nums.txt", X'
    with pytest.raises(PseudocodeError, match="CONSTANT"):
        run_src(src, tmp_path)


# ---- file-must-be-open / correct-mode enforcement (FR-9.1) ---------------


def test_readfile_without_opening_is_error(tmp_path):
    src = 'DECLARE X : STRING\nREADFILE "Missing.txt", X'
    with pytest.raises(PseudocodeError, match="not open"):
        run_src(src, tmp_path)


def test_writefile_without_opening_is_error(tmp_path):
    with pytest.raises(PseudocodeError, match="not open"):
        run_src('WRITEFILE "Missing.txt", "x"', tmp_path)


def test_readfile_on_file_opened_for_write_is_error(tmp_path):
    src = 'DECLARE X : STRING\nOPENFILE "Data.txt" FOR WRITE\nREADFILE "Data.txt", X'
    with pytest.raises(PseudocodeError, match="open for WRITE"):
        run_src(src, tmp_path)


def test_writefile_on_file_opened_for_read_is_error(tmp_path):
    (tmp_path / "Data.txt").write_text("1\n", encoding="utf-8")
    src = 'OPENFILE "Data.txt" FOR READ\nWRITEFILE "Data.txt", "x"'
    with pytest.raises(PseudocodeError, match="open for READ"):
        run_src(src, tmp_path)


def test_opening_an_already_open_file_is_error(tmp_path):
    src = 'OPENFILE "Data.txt" FOR WRITE\nOPENFILE "Data.txt" FOR WRITE'
    with pytest.raises(PseudocodeError, match="already open"):
        run_src(src, tmp_path)


def test_reopening_after_close_is_allowed(tmp_path):
    src = """
    OPENFILE "Data.txt" FOR WRITE
    WRITEFILE "Data.txt", "one"
    CLOSEFILE "Data.txt"
    OPENFILE "Data.txt" FOR WRITE
    WRITEFILE "Data.txt", "two"
    CLOSEFILE "Data.txt"
    """
    run_src(src, tmp_path)
    assert (tmp_path / "Data.txt").read_text(encoding="utf-8") == "two\n"


def test_closefile_on_unopened_file_is_error(tmp_path):
    with pytest.raises(PseudocodeError, match="not currently open"):
        run_src('CLOSEFILE "Data.txt"', tmp_path)


def test_openfile_read_missing_file_is_error(tmp_path):
    with pytest.raises(PseudocodeError, match="does not exist"):
        run_src('OPENFILE "Missing.txt" FOR READ', tmp_path)


def test_readfile_past_end_of_file_is_error(tmp_path):
    (tmp_path / "Data.txt").write_text("only line\n", encoding="utf-8")
    src = """
    DECLARE X : STRING
    OPENFILE "Data.txt" FOR READ
    READFILE "Data.txt", X
    READFILE "Data.txt", X
    """
    with pytest.raises(PseudocodeError, match="past the end"):
        run_src(src, tmp_path)


# ---- sandboxing (NFR-4) --------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    ["../secret.txt", "sub/dir.txt", "sub\\dir.txt", "..", "."],
)
def test_path_traversal_is_rejected(tmp_path, bad_name):
    with pytest.raises(PseudocodeError, match="not a valid file name"):
        run_src(f'OPENFILE "{bad_name}" FOR WRITE', tmp_path)


def test_file_identifier_must_be_a_string(tmp_path):
    with pytest.raises(PseudocodeError, match="must be a STRING"):
        run_src("OPENFILE 5 FOR WRITE", tmp_path)


def test_files_stay_within_file_root(tmp_path):
    src = 'OPENFILE "Data.txt" FOR WRITE\nWRITEFILE "Data.txt", "x"\nCLOSEFILE "Data.txt"'
    run_src(src, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Data.txt"]


# ---- whole-array guard, mirroring OUTPUT (FR-9.3) ------------------------


def test_writefile_whole_array_is_error(tmp_path):
    src = (
        "DECLARE Arr : ARRAY[1:3] OF INTEGER\n"
        'OPENFILE "Data.txt" FOR WRITE\n'
        'WRITEFILE "Data.txt", Arr'
    )
    with pytest.raises(PseudocodeError, match="array"):
        run_src(src, tmp_path)


def test_writefile_array_element_is_allowed(tmp_path):
    src = (
        "DECLARE Arr : ARRAY[1:3] OF INTEGER\n"
        "Arr[1] <- 7\n"
        'OPENFILE "Data.txt" FOR WRITE\n'
        'WRITEFILE "Data.txt", Arr[1]\n'
        'CLOSEFILE "Data.txt"'
    )
    run_src(src, tmp_path)
    assert (tmp_path / "Data.txt").read_text(encoding="utf-8") == "7\n"


# ---- files are auto-closed at the end of a run ---------------------------


def test_left_open_files_are_closed_automatically(tmp_path):
    src = 'OPENFILE "Data.txt" FOR WRITE\nWRITEFILE "Data.txt", "x"'
    _, interp = run_src(src, tmp_path)
    assert interp._open_files == {}
    # The write is flushed/closed even though the program never CLOSEFILEd it.
    assert (tmp_path / "Data.txt").read_text(encoding="utf-8") == "x\n"


def test_files_closed_automatically_even_after_an_error(tmp_path):
    src = 'OPENFILE "Data.txt" FOR WRITE\nWRITEFILE "Data.txt", "x"\nDECLARE X : INTEGER\nX <- "oops"'
    with pytest.raises(PseudocodeError):
        run_src(src, tmp_path)
    # The handle was closed by the interpreter's cleanup, so this doesn't hang
    # or raise, and the write that already happened made it to disk.
    assert (tmp_path / "Data.txt").read_text(encoding="utf-8") == "x\n"