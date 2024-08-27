#include "src/board.hh"

#include <cstdint>

#include <ti/devices/cc13x4_cc26x4/driverlib/cpu.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/gpio.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/ioc.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/prcm.h>

namespace board {

void BoardInit() {
  // Enable power domains.
  constexpr uint32_t kPowerDomains = PRCM_DOMAIN_PERIPH;

  PRCMPowerDomainOn(kPowerDomains);
  while (PRCMPowerDomainsAllOn(kPowerDomains) != PRCM_DOMAIN_POWER_ON) {}

  // Enable peripherals.
  constexpr uint32_t kPeripherals = PRCM_PERIPH_GPIO;
  PRCMPeripheralRunEnable(kPeripherals);

  // Initiate changes.
  PRCMLoadSet();
  while (!PRCMLoadGet()) {}

  // Configure IO.
  GPIO_clearDio(internal::kRedLedId);
  GPIO_clearDio(internal::kGreenLedId);
  IOCPortConfigureSet(internal::kRedLedId, IOC_PORT_GPIO, IOC_STD_OUTPUT);
  IOCPortConfigureSet(internal::kGreenLedId, IOC_PORT_GPIO, IOC_STD_OUTPUT);
  GPIO_setOutputEnableDio(internal::kRedLedId, GPIO_OUTPUT_ENABLE);
  GPIO_setOutputEnableDio(internal::kGreenLedId, GPIO_OUTPUT_ENABLE);
}

}  // namespace board
