#include "src/board.hh"

#include <cstdint>

#include <ti/devices/cc13x4_cc26x4/driverlib/cpu.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/gpio.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/ioc.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/prcm.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/sys_ctrl.h>
#include <ti/devices/cc13x4_cc26x4/driverlib/systick.h>

namespace board {

void BoardInit() {
  // Enable power domains.
  PRCMPowerDomainOn(PRCM_DOMAIN_PERIPH);
  while (PRCMPowerDomainsAllOn(PRCM_DOMAIN_PERIPH) != PRCM_DOMAIN_POWER_ON) {}

  // Enable peripherals.
  PRCMPeripheralRunEnable(PRCM_PERIPH_GPIO);

  // Initiate changes.
  PRCMLoadSet();
  while (!PRCMLoadGet()) {}

  // Configure IO.
  GPIO_clearDio(internal::kRedLedId);
  GPIO_clearDio(internal::kGreenLedId);
  IOCPortConfigureSet(internal::kRedLedId, IOC_PORT_GPIO, IOC_STD_OUTPUT);
  IOCPortConfigureSet(internal::kGreenLedId, IOC_PORT_GPIO, IOC_STD_OUTPUT);
  IOCPortConfigureSet(internal::kUart0RxId, IOC_PORT_MCU_UART0_RX, IOC_STD_INPUT);
  IOCPortConfigureSet(internal::kUart0TxId, IOC_PORT_MCU_UART0_TX, IOC_STD_OUTPUT);
  GPIO_setOutputEnableDio(internal::kRedLedId, GPIO_OUTPUT_ENABLE);
  GPIO_setOutputEnableDio(internal::kGreenLedId, GPIO_OUTPUT_ENABLE);

  // Setup SYSTICK and enable interrupt.
  const uint32_t kClockFreqHz = SysCtrlClockGet();
  const uint32_t kSysTickFreqHz = 1'000;
  SysTickPeriodSet(kClockFreqHz / kSysTickFreqHz);
  SysTickIntEnable();
  SysTickEnable();
}

}  // namespace board
