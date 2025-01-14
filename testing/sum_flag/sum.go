package main

// #include <Python.h>
// int PyArg_ParseTuple_ll(PyObject*, long*, long*);
import "C"

//export sum
func sum(self *C.PyObject, args *C.PyObject) *C.PyObject {
	var a C.long
	var b C.long
	if C.PyArg_ParseTuple_ll(args, &a, &b) == 0 {
		return nil
	}
	return C.PyLong_FromLong(a + b)
}

func main() {}
