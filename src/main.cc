#include "src/board.hh"

#include <cstdint>

#include <ti/devices/cc13x4_cc26x4/driverlib/cpu.h>

using board::GpioPin;

int main() {
  board::BoardInit();

  bool state = false;
  while (true) {
    if (state) {
      board::GpioSet(GpioPin::kRedLed);
      board::GpioClear(GpioPin::kGreenLed);
    } else {
      board::GpioClear(GpioPin::kRedLed);
      board::GpioSet(GpioPin::kGreenLed);
    }
    state = !state;

    constexpr uint32_t kDelayUs = 500'000;
    constexpr uint32_t kCpuFreqMhz = 48;
    constexpr uint32_t kCyclesPer = 4;
    CPUdelay(kDelayUs * (kCpuFreqMhz / kCyclesPer));
  }

  return 0;
}
