#include <ti/devices/cc13x4_cc26x4/driverlib/cpu.h>

// Dynamic memory allocation is not enabled or used.  However, virtual destructors require operator
// delete to be defined even though it will never be called.  We do not define the corresponding
// operator new stubs so that any inadvertent memory allocation is still a compile time error.

void operator delete(void * /*unused*/) {  // NOLINT(misc-new-delete-overloads)
  CPUcpsid();
  while (true) {}
}

void operator delete(void * /*unused*/, unsigned int /*unused*/) {
  CPUcpsid();
  while (true) {}
}
