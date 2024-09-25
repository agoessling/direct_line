#pragma once

#include <cstdint>

#include <ti/devices/cc13x4_cc26x4/driverlib/sys_ctrl.h>

namespace clock {

static inline uint32_t GetHfClockHz() {
  return SysCtrlClockGet();
}

}  // namespace clock
