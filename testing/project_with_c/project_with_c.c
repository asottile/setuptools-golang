#include <Python.h>

static PyObject* _hello_world(PyObject* self) {
    return PyUnicode_FromString("hello world");
}

static struct PyMethodDef methods[] = {
    {"hello_world", (PyCFunction)_hello_world, METH_NOARGS},
    {NULL, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "project_with_c",
    NULL,
    -1,
    methods
};

PyMODINIT_FUNC PyInit_project_with_c(void) {
    return PyModule_Create(&module);
}
