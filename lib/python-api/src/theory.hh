#pragma once

#include <Python.h>

namespace PyClingo {

//! Create the clingo_funasp.theory module with its own types and functions (first registration phase).
auto create_theory(PyObject *parent) -> PyObject *;
//! Store the types of other modules in the state of the clingo_funasp.theory module (second registration phase).
auto link_theory(PyObject *mod) -> bool;

} // namespace PyClingo
