#include <exception>

#include <ti/devices/cc13x4_cc26x4/driverlib/cpu.h>

// Fatal C++ library contract failures use the same halt policy as firmware assertions.
[[noreturn]] void std::terminate() noexcept {
  CPUcpsid();
  while (true) {}
}

extern "C" {
// There is one statically linked image and it never exits or unloads. GCC still passes a DSO
// handle when registering global destructors, even with -fno-exceptions and -nostartfiles.
void *__dso_handle = nullptr;

// ResetHandler deliberately never runs global destructors. Do not register them with newlib:
// its exit registry is unnecessary here and may allocate. Local RAII destruction is unaffected.
int __aeabi_atexit(void * /*object*/, void (* /*destructor*/)(void *),
                   void * /*dso_handle*/) noexcept {
  return 0;
}
}

// Dynamic memory allocation is not enabled or used.  However, virtual destructors require operator
// delete to be defined even though it will never be called.  We do not define the corresponding
// operator new stubs so that any inadvertent memory allocation is still a link-time error.

void operator delete(void * /*unused*/) {  // NOLINT(misc-new-delete-overloads)
  std::terminate();
}

void operator delete(void * /*unused*/, unsigned int /*unused*/) {
  std::terminate();
}
