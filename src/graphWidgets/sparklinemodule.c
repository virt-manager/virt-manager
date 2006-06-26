#include <pygobject.h>

void sparkline_register_classes (PyObject *d);
extern PyMethodDef sparkline_functions[];

DL_EXPORT(void)
initsparkline(void)
{
    PyObject *m, *d;

    init_pygobject ();

    m = Py_InitModule ("sparkline", sparkline_functions);
    d = PyModule_GetDict (m);

    sparkline_register_classes(d);

    if (PyErr_Occurred ()) {
        Py_FatalError ("can't initialise module sparkline");
    }
}
