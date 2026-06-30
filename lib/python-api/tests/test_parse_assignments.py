import tempfile, os

from clingo_funasp import core, ast

class TestParseString():

    def setup_method(self):
        self.lib = core.Library()

    def assert_location(self, statement, file_name=None):
        if file_name is None:
            file_name = "<string>"
            def basename(file_name):
                return file_name
        else:
            file_name = os.path.basename(file_name)
            def basename(file_name):
                return os.path.basename(file_name)
        location = statement.location
        if hasattr(statement, "head") and hasattr(statement.head, "literal"):
            literal = statement.head.literal
            if hasattr(literal, "atom"):
                atom_location = literal.atom.location
                assert basename(atom_location.begin.file) == file_name
                assert basename(atom_location.end.file) == file_name
            literal_location = literal.location
            assert basename(literal_location.end.file) == file_name
            assert basename(literal_location.begin.file) == file_name

        if hasattr(statement, "head") and hasattr(statement.head, "location"):
            head = statement.head
            if hasattr(head, "left") and hasattr(head.left, "term") and hasattr(head.left.term, "location"):
                left_location = head.left.term.location
                assert basename(left_location.end.file) == file_name
                assert basename(left_location.begin.file) == file_name
            location_head = head.location
            assert basename(location_head.end.file) == file_name
            assert basename(location_head.begin.file) == file_name
            pass
        assert basename(location.end.file) == file_name
        assert basename(location.begin.file) == file_name

    def parse_string(self, s):
        statements = []
        ast.parse_string(self.lib, s, lambda x: statements.append(x))
        if isinstance(statements[0], ast.StatementProgram):
            statements = statements[1:]
        self.assert_location(statements[0])
        return "\n".join(map(str, statements))

    def parse_with_file(self, s):
        fd, path = tempfile.mkstemp(text=True, suffix=".lp")
        try:
            with os.fdopen(fd, "w") as temp_file:
                temp_file.write(s)
                temp_file.write("\n")
            statements = []
            ast.parse_files(self.lib, [path], lambda x: statements.append(x))
            if statements and isinstance(statements[0], ast.StatementProgram):
                statements = statements[1:]
            self.assert_location(statements[0], file_name=path)
            return "\n".join(map(str, statements))
        finally:
            os.unlink(path)

    def test_parse_string(self):
        assert self.parse_string("a.") == "a."
        assert self.parse_string("a(b).") == "a(b)."
        assert self.parse_string("a(b,c).") == "a(b,c)."
        assert self.parse_string("a(b,c,d).") == "a(b,c,d)."

    def test_parse_string_assignments(self):
        assert self.parse_string("a := 1.") == "Fa(1)."
        assert self.parse_string("a(b) := 1.") == "Fa(b,1)."
        assert self.parse_string("a(b,c) := 1.") == "Fa(b,c,1)."
        assert self.parse_string("a(b,c,d) := 1.") == "Fa(b,c,d,1)."

    def test_parse_string_assignments_with_aggregates(self):
        assert self.parse_string("a := #sum{ X : p(X)}.") == "Fa = #sum { X: NONE: p(X) }."
        assert self.parse_string("a(b) := #sum{ X : p(X)}.") == "Fa(b) = #sum { X: NONE: p(X) }."
        assert self.parse_string("a := #some{ X : p(X)}.") == "FSa = #sum { X: NONE: p(X) }."
        assert self.parse_string("a(b) := #some{ X : p(X)}.") == "FSa(b) = #sum { X: NONE: p(X) }."

    def test_parse_string_assignments_in_aggregates(self):
        assert self.parse_string("#sum{ X : a := X : p(X)}.") == "#sum { X: Fa(X): p(X) }."
        assert self.parse_string("#sum{ X : a(b) := X : p(X)}.") == "#sum { X: Fa(b,X): p(X) }."

    def test_showf(self):
        assert self.parse_string("#showf a/0.") == "#show Fa/1. [true]"
        assert self.parse_string("#showf a/1.") == "#show Fa/2. [true]"

    def test_pool(self):
        assert self.parse_string("p(b;c).") == "p(b;c)."
        assert self.parse_string("f(b;c) := 1.") == "Ff(b,1;c,1)."

    def test_file_string(self):
        assert self.parse_with_file("a.") == "a."
        assert self.parse_with_file("a(b).") == "a(b)."
        assert self.parse_with_file("a(b,c).") == "a(b,c)."
        assert self.parse_with_file("a(b,c,d).") == "a(b,c,d)."

    def test_file_string_assignments(self):
        assert self.parse_with_file("a := 1.") == "Fa(1)."
        assert self.parse_with_file("a(b) := 1.") == "Fa(b,1)."
        assert self.parse_with_file("a(b,c) := 1.") == "Fa(b,c,1)."
        assert self.parse_with_file("a(b,c,d) := 1.") == "Fa(b,c,d,1)."

    def test_file_string_assignments_with_aggregates(self):
        assert self.parse_with_file("a := #sum{ X : p(X)}.") == "Fa = #sum { X: NONE: p(X) }."
        assert self.parse_with_file("a(b) := #sum{ X : p(X)}.") == "Fa(b) = #sum { X: NONE: p(X) }."
        assert self.parse_with_file("a := #some{ X : p(X)}.") == "FSa = #sum { X: NONE: p(X) }."
        assert self.parse_with_file("a(b) := #some{ X : p(X)}.") == "FSa(b) = #sum { X: NONE: p(X) }."

    def test_file_string_assignments_with_aggregates_and_pools(self):
        assert self.parse_with_file("a(b;c) := #sum{ X : p(X)}.") == "Fa(b;c) = #sum { X: NONE: p(X) }."

    def test_file_string_assignments_in_aggregates(self):
        assert self.parse_with_file("#sum{ X : a := X : p(X)}.") == "#sum { X: Fa(X): p(X) }."
        assert self.parse_with_file("#sum{ X : a(b) := X : p(X)}.") == "#sum { X: Fa(b,X): p(X) }."

    def test_file_string_assignments_in_aggregates_and_pools(self):
        assert self.parse_with_file("#sum{ X : a(b;c) := X : p(X)}.") == "#sum { X: Fa(b,X;c,X): p(X) }."

    def test_file_showf(self):
        assert self.parse_with_file("#showf a/0.") == "#show Fa/1. [true]"
        assert self.parse_with_file("#showf a/1.") == "#show Fa/2. [true]"

    def test_pool_with_file(self):
        assert self.parse_with_file("p(b;c).") == "p(b;c)."
        assert self.parse_with_file("f(b;c) := 1.") == "Ff(b,1;c,1)."