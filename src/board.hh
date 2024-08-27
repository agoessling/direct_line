#pragma once

#include <cstdint>
#include <array>

#include <ti/devices/cc13x4_cc26x4/driverlib/gpio.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/ioc.h>

namespace board {

enum class GpioPin {
  kRedLed,
  kGreenLed,
};

namespace internal {

constexpr uint32_t kRedLedId = IOID_6;
constexpr uint32_t kGreenLedId = IOID_7;

constexpr uint32_t GpioPinMapping(GpioPin pin) {
  constexpr std::array<uint32_t, 2> kGpioMapping = {
      kRedLedId,
      kGreenLedId,
  };
  return kGpioMapping[static_cast<uint32_t>(pin)];
}

static_assert(GpioPinMapping(GpioPin::kRedLed) == kRedLedId);
static_assert(GpioPinMapping(GpioPin::kGreenLed) == kGreenLedId);

}  // namespace internal

void BoardInit();

static inline void GpioSet(GpioPin pin) {
  GPIO_setDio(internal::GpioPinMapping(pin));
}

static inline void GpioClear(GpioPin pin) {
  GPIO_clearDio(internal::GpioPinMapping(pin));
}

static inline void GpioWrite(GpioPin pin, bool value) {
  GPIO_writeDio(internal::GpioPinMapping(pin), static_cast<uint32_t>(value));
}

static inline void GpioToggle(GpioPin pin) {
  GPIO_toggleDio(internal::GpioPinMapping(pin));
}

}  // namespace board
