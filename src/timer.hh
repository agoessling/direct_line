#pragma once

#include <cstdint>

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
  [[nodiscard]] uint32_t cycles_per_us() const noexcept { return cycles_per_us_; }
  void Reset() noexcept;

 private:
  volatile GptPeriphDef *timer_;
  uint32_t interrupt_;
  uint32_t cycles_per_us_;
};

class PeriodicTimer : public BaseTimer {
 public:
  PeriodicTimer(Id id, interrupt::Priority priority) noexcept;
  void SetPeriod(uint32_t period_us) noexcept;
  void ClearInterrupt() noexcept;
};

class RunningTimer : public BaseTimer {
 public:
  explicit RunningTimer(Id id) noexcept;
  [[nodiscard]] int64_t NowUs() noexcept;

 private:
  uint32_t us_per_overflow_;
  int64_t running_timer_us_ = 0;
  uint32_t last_timer_val_ = 0;
};

}  // namespace timer
