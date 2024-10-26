#pragma once

#include <source_location>
#include <string_view>

#include <ti/devices/cc13x4_cc26x4/driverlib/cpu.h>

static inline void Assert(bool expr, std::string_view description = "",
                          std::source_location location = std::source_location::current()) {
  (void)description;
  (void)location;
  if (!expr) {
    CPUcpsid();  // Disable interrupts.
    while (true) {}
  }
}
