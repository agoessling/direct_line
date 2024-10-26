#include "src/timer.hh"
#include "src/assert.hh"

#include <cstdint>

#include <ti/devices/cc13x4_cc26x4/driverlib/interrupt.h>

#include "src/clock.hh"
#include "src/interrupt.hh"

namespace timer {

BaseTimer::BaseTimer(Id id) noexcept {
  uint32_t peripheral = 0;
  switch (id) {
    case Id::kTimer0:
      timer_ = GPT0;
      interrupt_ = INT_GPT0A;
      peripheral = PRCM_PERIPH_TIMER0;
      break;
    case Id::kTimer1:
      timer_ = GPT1;
      interrupt_ = INT_GPT1A;
      peripheral = PRCM_PERIPH_TIMER1;
      break;
    case Id::kTimer2:
      timer_ = GPT2;
      interrupt_ = INT_GPT2A;
      peripheral = PRCM_PERIPH_TIMER2;
      break;
    case Id::kTimer3:
      timer_ = GPT3;
      interrupt_ = INT_GPT3A;
      peripheral = PRCM_PERIPH_TIMER3;
      break;
  }

  // Enable power domain and peripheral.
  PRCMPowerDomainOn(PRCM_DOMAIN_PERIPH);
  while (PRCMPowerDomainsAllOn(PRCM_DOMAIN_PERIPH) != PRCM_DOMAIN_POWER_ON) {}

  PRCMPeripheralRunEnable(peripheral);

  // Initiate changes.
  PRCMLoadSet();
  while (!PRCMLoadGet()) {}

  Reset();

  // Assume GPT clock is greater than and a multiple of 1MHz.
  const uint32_t gpt_clock_hz = clock::GetGptClockHz();
  Assert(gpt_clock_hz != 0);
  Assert(gpt_clock_hz % 1'000'000 == 0);

  cycles_per_us_ = gpt_clock_hz / 1'000'000;
}

void BaseTimer::Reset() noexcept {
  timer_->CTL.raw = 0;
  timer_->CFG.raw = 0;
  timer_->TAMR.raw = 0;
  timer_->TBMR.raw = 0;
  timer_->IMR.raw = 0;
  timer_->ICLR.raw = 0xFFFFFFFF;
}

PeriodicTimer::PeriodicTimer(Id id, interrupt::Priority priority) noexcept : BaseTimer(id) {
  timer()->TAMR.TAILD = 1;  // Load timeout value at next timeout instead of immediately.
  timer()->TAMR.TAMR = 0x2;  // Periodic mode.
  timer()->IMR.TATOIM = 1;  // Enable timer time out interrupt.

  IntPrioritySet(interrupt(), interrupt::DriverLibPriorityLevel(priority));
  IntEnable(interrupt());
}

void PeriodicTimer::SetPeriod(uint32_t period_us) noexcept {
  timer()->TAILR.TAILR = cycles_per_us() * period_us;
}

ClockTimer::ClockTimer(Id id) noexcept : BaseTimer(id) {
  timer()->TAMR.TAMR = 0x2;  // Periodic mode.
  timer()->TAMR.TACDIR = 0x1;  // Count up.

  // Use biggest period which is a multiple of cycles_per_us.
  const uint32_t load_value = 0xFFFFFFFF - (0xFFFFFFFF % cycles_per_us());
  us_per_overflow_ = load_value / cycles_per_us();

  timer()->TAILR.TAILR = load_value;
}

int64_t ClockTimer::NowUs() noexcept {
  int64_t running_timer_us = 0;
  uint32_t current_val = 0;
  interrupt::CriticalSection([&]() noexcept {
    current_val = timer()->TAV.TAV;
    if (current_val < last_timer_val_) {
      running_timer_us_ += us_per_overflow_;
    }
    last_timer_val_ = current_val;
    running_timer_us = running_timer_us_;
  });
  return running_timer_us + current_val / cycles_per_us();
}

WrappingTimer::WrappingTimer(Id id) noexcept : BaseTimer(id) {
  timer()->TAMR.TAMR = 0x2;  // Periodic mode.
  timer()->TAMR.TACDIR = 0x1;  // Count up.
  timer()->TAILR.TAILR = 0xFFFFFFFF;
}

};  // namespace timer
