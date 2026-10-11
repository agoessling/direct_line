#include <ti/devices/cc13x4_cc26x4/driverlib/rom.h>

// Expose the ROM macro to Rust using TI's function-table layout and signature.
void ti_hf_source_safe_switch(void) { HapiHFSourceSafeSwitch(); }
