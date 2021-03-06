#include <Python.h>

/* Will come from go */
PyObject* sum(PyObject* , PyObject*);

/* To shim go's missing variadic function support */
int PyArg_ParseTuple_ll(PyObject* args, long* a, long* b) {
    return PyArg_ParseTuple(args, "ll", a, b);
}

static struct PyMethodDef methods[] = {
    {"sum", (PyCFunction)sum, METH_VARARGS},
    {NULL, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "project_with_c_sum.sum",
    NULL,
    -1,
    methods
};

PyMODINIT_FUNC PyInit_sum(void) {
    return PyModule_Create(&module);
}
