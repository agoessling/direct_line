#include "src/uart.hh"

#include <cstdint>
#include <expected>

#include "src/cc1354p10_reg_def.h"
#include "src/clock.hh"

namespace uart {

Uart::Uart(Id id) {
  switch (id) {
    case Id::kUart0:
      uart_ = UART0;
      break;
    case Id::kUart1:
      uart_ = UART1;
      break;
    case Id::kUart2:
      uart_ = UART2;
      break;
    case Id::kUart3:
      uart_ = UART3;
      break;
  }

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
