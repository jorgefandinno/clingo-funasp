#include "clingo.hh"

// NOLINTNEXTLINE
PyMODINIT_FUNC PyInit_clingo_funasp() {
    return PyClingo::init_clingo();
}
