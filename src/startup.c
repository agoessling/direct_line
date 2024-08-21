#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <ti/devices/cc13x4_cc26x4/driverlib/setup.h>

// NOLINTBEGIN(bugprone-reserved-identifier, cppcoreguidelines-avoid-non-const-global-variables)

// Exported from linker script.
// Reminder: the addresses of these are equal to the linker script labels.
extern uint32_t _estack;  // End of stack memory region. (initial stack pointer)
extern uint32_t _sidata;  // Start of initialization for .data section.
extern uint32_t _sdata;  // Start of .data section.
extern uint32_t _edata;  // End of .data section.
extern uint32_t _sbss;  // Start of .bss section.
extern uint32_t _ebss;  // End of .bss section.
void (*__preinit_array_start)(void);  // Start of preinit function array.
void (*__preinit_array_end)(void);  // End of preinit function array.
void (*__init_array_start)(void);  // Start of preinit function array.
void (*__init_array_end)(void);  // End of preinit function array.
//
// NOLINTEND(bugprone-reserved-identifier, cppcoreguidelines-avoid-non-const-global-variables)

int main(void);  // Application main

void ResetHandler(void) {
  // This is redundant as SP is set on reset based on the first entry of the vector table.  However,
  // for whatever reason, the TI debugger does not acheive this when launching and requires it to be
  // explicitly set.
  __asm volatile(
      "LDR r0, =_estack\n"
      "MSR msp, r0");

  // Enable the floating point unit.
  volatile uint32_t *const CPACR = (volatile uint32_t *)0xE000ED88;
  *CPACR |= (0x0F << 20);  // NOLINT(readability-magic-numbers)

  SetupTrimDevice();

  uint32_t *src;  // NOLINT(cppcoreguidelines-init-variables)
  uint32_t *dst;  // NOLINT(cppcoreguidelines-init-variables)

  // Copy .data section by words.  This relies on .data being word aligned via linker script.
  src = &_sidata;
  dst = &_sdata;
  while (dst < &_edata) {
    *dst++ = *src++;
  }

  // Zero .bss seciton by words.  This relies on .bss being word aligned via linker script.
  dst = &_sbss;
  while (dst < &_ebss) {
    *dst++ = 0;
  }

  // Static initialization functions aggregated by compiler into .preinit_array and .init_array.
  void (**func)(void);  // NOLINT(cppcoreguidelines-init-variables)

  func = &__preinit_array_start;
  while (func < &__preinit_array_end) {
    (*func++)();
  }

  func = &__init_array_start;
  while (func < &__init_array_end) {
    (*func++)();
  }

  (void)main();

  // NOTE: Static deinitialization functions are not handled as they don't make sense in an embedded
  // context.

  // Catch if main() returns.
  while (true) {
  }
}

// clang-format off

// Create default traps for all interrupts.
// In order to utilize a more interesting interrupt handler, replace the static handler definition
// below with a non-static declaration.
static void NmiHandler(void) { while(true) {} }
static void HardFaultHandler(void) { while(true) {} }
static void MemManageHandler(void) { while(true) {} }
static void BusFaultHandler(void) { while(true) {} }
static void UsageFaultHandler(void) { while(true) {} }
static void SecureFaultHandler(void) { while(true) {} }
static void SvcHandler(void) { while(true) {} }
static void DebugMonitorHandler(void) { while(true) {} }
static void PendSvHandler(void) { while(true) {} }
static void SysTickHandler(void) { while(true) {} }
static void GpioHandler(void) { while(true) {} }
static void I2c0Handler(void) { while(true) {} }
static void RfCcPe1Handler(void) { while(true) {} }
static void PkaHandler(void) { while(true) {} }
static void AonRtcHandler(void) { while(true) {} }
static void Uart0Handler(void) { while(true) {} }
static void AuxSwEvent0Handler(void) { while(true) {} }
static void Ssi0Handler(void) { while(true) {} }
static void Ssi1Handler(void) { while(true) {} }
static void RfCcPe0Handler(void) { while(true) {} }
static void RfcHardwareHandler(void) { while(true) {} }
static void RfcCmdAckHandler(void) { while(true) {} }
static void I2sHandler(void) { while(true) {} }
static void AuxSwEvent1Handler(void) { while(true) {} }
static void WatchdogHandler(void) { while(true) {} }
static void Timer0AHandler(void) { while(true) {} }
static void Timer0BHandler(void) { while(true) {} }
static void Timer1AHandler(void) { while(true) {} }
static void Timer1BHandler(void) { while(true) {} }
static void Timer2AHandler(void) { while(true) {} }
static void Timer2BHandler(void) { while(true) {} }
static void Timer3AHandler(void) { while(true) {} }
static void Timer3BHandler(void) { while(true) {} }
static void CryptoHandler(void) { while(true) {} }
static void UdmaHandler(void) { while(true) {} }
static void UdmaErrHandler(void) { while(true) {} }
static void FlashHandler(void) { while(true) {} }
static void SwEvent0Handler(void) { while(true) {} }
static void AuxCombEventHandler(void) { while(true) {} }
static void AonProgHandler(void) { while(true) {} }
static void DynProgHandler(void) { while(true) {} }
static void AuxCompAHandler(void) { while(true) {} }
static void AuxAdcHandler(void) { while(true) {} }
static void TrngHandler(void) { while(true) {} }
static void OscHandler(void) { while(true) {} }
static void AuxTimer2Handler(void) { while(true) {} }
static void Uart1Handler(void) { while(true) {} }
static void BatMonHandler(void) { while(true) {} }
static void Ssi2Handler(void) { while(true) {} }
static void Ssi3Handler(void) { while(true) {} }
static void Uart2Handler(void) { while(true) {} }
static void Uart3Handler(void) { while(true) {} }
static void I2c1Handler(void) { while(true) {} }
static void SwEv1Handler(void) { while(true) {} }
static void SwEv2Handler(void) { while(true) {} }
static void SwEv3Handler(void) { while(true) {} }
static void SwEv4Handler(void) { while(true) {} }

// NOLINTNEXTLINE(cppcoreguidelines-interfaces-global-init)
__attribute__((section(".isr_vector"))) void (* const isr_vectors[])(void) = {
  (void (* const)(void))&_estack,
  ResetHandler,
  NmiHandler,
  HardFaultHandler,
  MemManageHandler,
  BusFaultHandler,
  UsageFaultHandler,
  SecureFaultHandler,
  NULL,
  NULL,
  NULL,
  SvcHandler,
  DebugMonitorHandler,
  NULL,
  PendSvHandler,
  SysTickHandler,
  // External interrupts.
  GpioHandler,          // 16 AON edge detect
  I2c0Handler,          // 17 I2C0
  RfCcPe1Handler,       // 18 RF Core Command & Packet Engine 1
  PkaHandler,           // 19 PKA Interrupt event
  AonRtcHandler,        // 20 AON RTC
  Uart0Handler,         // 21 UART0 Rx and Tx
  AuxSwEvent0Handler,   // 22 AUX software event 0
  Ssi0Handler,          // 23 SSI0 Rx and Tx
  Ssi1Handler,          // 24 SSI1 Rx and Tx
  RfCcPe0Handler,       // 25 RF Core Command & Packet Engine 0
  RfcHardwareHandler,   // 26 RF Core Hardware
  RfcCmdAckHandler,     // 27 RF Core Command Acknowledge
  I2sHandler,           // 28 I2S
  AuxSwEvent1Handler,   // 29 AUX software event 1
  WatchdogHandler,      // 30 Watchdog timer
  Timer0AHandler,       // 31 Timer 0 subtimer A
  Timer0BHandler,       // 32 Timer 0 subtimer B
  Timer1AHandler,       // 33 Timer 1 subtimer A
  Timer1BHandler,       // 34 Timer 1 subtimer B
  Timer2AHandler,       // 35 Timer 2 subtimer A
  Timer2BHandler,       // 36 Timer 2 subtimer B
  Timer3AHandler,       // 37 Timer 3 subtimer A
  Timer3BHandler,       // 38 Timer 3 subtimer B
  CryptoHandler,        // 39 Crypto Core Result available
  UdmaHandler,          // 40 uDMA Software
  UdmaErrHandler,       // 41 uDMA Error
  FlashHandler,         // 42 Flash controller
  SwEvent0Handler,      // 43 Software Event 0
  AuxCombEventHandler,  // 44 AUX combined event
  AonProgHandler,       // 45 AON programmable 0
  DynProgHandler,       // 46 Dynamic Programmable interrupt source (Default: PRCM)
  AuxCompAHandler,      // 47 AUX Comparator A
  AuxAdcHandler,        // 48 AUX ADC new sample or ADC DMA done, ADC underflow, ADC overflow
  TrngHandler,          // 49 TRNG event
  OscHandler,           // 50 Combined event from Oscillator control
  AuxTimer2Handler,     // 51 AUX Timer2 event 0
  Uart1Handler,         // 52 UART1 combined interrupt
  BatMonHandler,        // 53 Combined event from battery monitor
  Ssi2Handler,          // 54 SSI2 combined interrupt
  Ssi3Handler,          // 55 SSI3 combined interrupt
  Uart2Handler,         // 56 UART2 combined interrupt
  Uart3Handler,         // 57 UART3 combined interrupt
  I2c1Handler,          // 58 Interrupt event from I2C1
  SwEv1Handler,         // 59 Software callback event 1
  SwEv2Handler,         // 60 Software callback event 2
  SwEv3Handler,         // 61 Software callback event 3
  SwEv4Handler          // 62 Software callback event 4
};
// clang-format on
