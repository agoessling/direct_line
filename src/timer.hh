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

class BaseTimer {
 public:
  void Start() noexcept;
  void Stop() noexcept;

 protected:
  explicit BaseTimer(Id id) noexcept;
  [[nodiscard]] volatile GptPeriphDef *timer() const noexcept { return timer_; }
  [[nodiscard]] uint32_t interrupt() const noexcept { return interrupt_; }
  void Reset() noexcept;

 private:
  volatile GptPeriphDef *timer_;
  uint32_t interrupt_;
};

class PeriodicTimer : public BaseTimer {
 public:
  PeriodicTimer(Id id, interrupt::Priority priority) noexcept;
  void SetPeriod(uint32_t period_us) noexcept;
  void ClearInterrupt() noexcept;
};

}  // namespace timer
