#include "src/uart.hh"

#include <cstdint>
#include <expected>

#include <ti/devices/cc13x4_cc26x4/driverlib/prcm.h>

#include "src/cc1354p10_reg_def.h"
#include "src/clock.hh"

namespace uart {

Uart::Uart(Id id) {
  uint32_t power_domain = 0;
  uint32_t peripheral = 0;
  switch (id) {
    case Id::kUart0:
      uart_ = UART0;
      power_domain = PRCM_DOMAIN_SERIAL;
      peripheral = PRCM_PERIPH_UART0;
      break;
    case Id::kUart1:
      uart_ = UART1;
      power_domain = PRCM_DOMAIN_PERIPH;
      peripheral = PRCM_PERIPH_UART1;
      break;
    case Id::kUart2:
      uart_ = UART2;
      power_domain = PRCM_DOMAIN_PERIPH;
      peripheral = PRCM_PERIPH_UART2;
      break;
    case Id::kUart3:
      uart_ = UART3;
      power_domain = PRCM_DOMAIN_PERIPH;
      peripheral = PRCM_PERIPH_UART3;
      break;
  }

  // Enable power domain and peripheral.
  PRCMPowerDomainOn(power_domain);
  while (PRCMPowerDomainsAllOn(power_domain) != PRCM_DOMAIN_POWER_ON) {}

  PRCMPeripheralRunEnable(peripheral);

  // Initiate changes.
  PRCMLoadSet();
  while (!PRCMLoadGet()) {}

  Reset();
}

void Uart::Reset() {
  uart_->CTL.raw = 0;
  uart_->LCRH.raw = 0;
  uart_->DMACTL.raw = 0;
}

std::expected<void, Error> Uart::Configure(const Config& config) {
  Reset();

  // Configure baudrate. (TRM 22.4.2)
  const uint32_t uart_clk_freq_hz = clock::GetHfClockHz();
  const uint32_t denom = 16U * config.baudrate;
  const uint32_t brdi = uart_clk_freq_hz / denom;
  const uint32_t brdf = ((uart_clk_freq_hz % denom) * 64 + denom / 2) / denom;

  // Check validity of baudrate divisors. (TRM 22.7.5)
  if (brdi < 1 || brdi >= (1 << 16) || ((brdi == (1 << 16) - 1) && (brdf != 0u)) ||
      brdf >= (1 << 6)) {
    return std::unexpected(Error::kInvalidBaud);
  }

  uart_->IBRD.DIVINT = brdi;
  uart_->FBRD.DIVFRAC = brdf;

  // 8 bit word length.
  uart_->LCRH.WLEN = 0x3;

  // Enable UART
  uart_->CTL.RXE = config.rx_enable;
  uart_->CTL.TXE = config.tx_enable;
  uart_->CTL.UARTEN = true;

  return {};
}

void Uart::Send(uint8_t byte) {
  while (uart_->FR.TXFF) {}
  uart_->DR.DATA = byte;
}

void Uart::Send(char c) {
  Send(static_cast<uint8_t>(c));
}

void Uart::Send(std::span<const uint8_t> data) {
  for (const uint8_t byte : data) {
    Send(byte);
  }
}

void Uart::Send(std::string_view str) {
  for (const char c : str) {
    Send(c);
  }
}

}  // namespace uart
