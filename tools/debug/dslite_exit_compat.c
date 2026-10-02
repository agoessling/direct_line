#include <stdio.h>
#include <stdlib.h>

// Optional Linux host workaround, loaded into DSLite only via LD_PRELOAD.
// On the affected host, DebugServer calls exit() from a worker and deadlocks while
// destroying a main-thread condition variable. Keep the requested exit status and
// flush C stdio, but bypass atexit handlers and process-global destructor cleanup.
// This changes shutdown behavior; it does not turn failed flash operations into
// successful ones. Use only when this DebugServer shutdown hang has been observed.
// Build: cc -shared -fPIC dslite_exit_compat.c -o /tmp/dslite_exit_compat.so
_Noreturn void exit(int status) {
  fflush(NULL);
  _Exit(status);
}
