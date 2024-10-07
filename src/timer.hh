#pragma once

#include <expected>

#include "src/cc1354p10_reg_def.h"
#include "src/interrupt.hh"

namespace timer {

enum class Id {
  kTimer0,
  kTimer1,
  kTimer2,
  kTimer3,
};

enum class Error {};

class PeriodicTimer {
 public:
  struct Config {
    uint32_t period_us;
    bool enable_interrupt;
  };

  explicit PeriodicTimer(Id id, interrupt::Priority priority);
  void SetPeriod(uint32_t period_us);
  void Start();
  void Stop();
  void ClearInterrupt();

 private:
  void Reset();

  volatile GptPeriphDef *timer_;
};

}  // namespace timer
