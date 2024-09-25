#pragma once

#include <cstdint>
#include <expected>
#include <span>
#include <string_view>

#include "src/cc1354p10_reg_def.h"

namespace uart {

enum class Id {
  kUart0,
  kUart1,
  kUart2,
  kUart3,
};

enum class Error {
  kInvalidBaud,
};

struct Config {
  bool rx_enable = true;
  bool tx_enable = true;
  uint32_t baudrate = 115200;
};

class Uart {
 public:
  explicit Uart(Id id);
  std::expected<void, Error> Configure(const Config& config = Config());

  void Send(uint8_t byte);
  void Send(char c);
  void Send(std::span<const uint8_t> data);
  void Send(std::string_view str);

 private:
  void Reset();

  volatile UartPeriphDef *uart_;
};
}  // namespace uart
