#pragma once

#include <cstdint>

#include <ti/devices/cc13x4_cc26x4/driverlib/prcm.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/sys_ctrl.h>

namespace clock {

static inline uint32_t GetHfClockHz() {
  return SysCtrlClockGet();
}

static inline uint32_t GetGptClockHz() {
  const uint32_t hf_clock_hz = GetHfClockHz();
  switch (PRCMGPTimerClockDivisionGet()) {
    case PRCM_CLOCK_DIV_1:
      return hf_clock_hz;
    case PRCM_CLOCK_DIV_2:
      return hf_clock_hz / 2;
    case PRCM_CLOCK_DIV_4:
      return hf_clock_hz / 4;
    case PRCM_CLOCK_DIV_8:
      return hf_clock_hz / 8;
    case PRCM_CLOCK_DIV_16:
      return hf_clock_hz / 16;
    case PRCM_CLOCK_DIV_32:
      return hf_clock_hz / 32;
    case PRCM_CLOCK_DIV_64:
      return hf_clock_hz / 64;
    case PRCM_CLOCK_DIV_128:
      return hf_clock_hz / 128;
    case PRCM_CLOCK_DIV_256:
      return hf_clock_hz / 256;
    default:
      return 1;
  }
}

}  // namespace clock
