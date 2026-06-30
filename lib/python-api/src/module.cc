#include "clingo.hh"

PYBIND11_MODULE(clingo_funasp, m) {
    PyClingo::register_clingo(m);
}
