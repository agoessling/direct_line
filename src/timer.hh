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

// Base class for timers.
class BaseTimer {
 public:
  // Starts the timer.
  void Start() noexcept { timer_->CTL.TAEN = 1; }
  // Stops the timer.
  void Stop() noexcept { timer_->CTL.TAEN = 0; }

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

// Periodic timer which triggers an interrupt at the configured period.
class PeriodicTimer : public BaseTimer {
 public:
  PeriodicTimer(Id id, interrupt::Priority priority) noexcept;
  // Set the period of the interrupt.
  void SetPeriod(uint32_t period_us) noexcept;
  // Clears the timer interrupt.  Must be called in the associated ISR.
  void ClearInterrupt() noexcept;
};

// Timer which indefinitely increments and provides microseconds since start.  NowUs() must be
// called at least once per ~90 seconds.
class ClockTimer : public BaseTimer {
 public:
  explicit ClockTimer(Id id) noexcept;

  // Returns the number of microseconds since start. *NOTE:* This function contains a bounded length
  // critical section during which interrupts are disabled.  This function must be called at least
  // once every ~90 seconds to avoid losing time.
  [[nodiscard]] int64_t NowUs() noexcept;

 private:
  uint32_t us_per_overflow_;
  int64_t running_timer_us_ = 0;
  uint32_t last_timer_val_ = 0;
};

class WrappingTimer : public BaseTimer {
 public:
  explicit WrappingTimer(Id id) noexcept;

  // Returns the current number of cycles.  The value wraps on overflow.
  [[nodiscard]] uint32_t Now() noexcept { return timer()->TAV.TAV; }

  // Returns the number of cycles returned by Now() in a single microsecond.
  [[nodiscard]] uint32_t CyclesPerUs() noexcept { return cycles_per_us(); }
};

// Implementation.

inline void PeriodicTimer::ClearInterrupt() noexcept {
  GptIclrRegDef reg;
  reg.raw = 0;
  reg.TATOCINT = 1;
  timer()->ICLR.raw = reg.raw;
}

}  // namespace timer
