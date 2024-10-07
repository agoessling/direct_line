#include "src/timer.hh"

#include <ti/devices/cc13x4_cc26x4/driverlib/interrupt.h>

#include "src/clock.hh"
#include "src/interrupt.hh"

namespace timer {

PeriodicTimer::PeriodicTimer(Id id, interrupt::Priority priority) {
  uint32_t peripheral = 0;
  uint32_t interrupt = 0;
  switch (id) {
    case Id::kTimer0:
      timer_ = GPT0;
      peripheral = PRCM_PERIPH_TIMER0;
      interrupt = INT_GPT0A;
      break;
    case Id::kTimer1:
      timer_ = GPT1;
      peripheral = PRCM_PERIPH_TIMER1;
      interrupt = INT_GPT1A;
      break;
    case Id::kTimer2:
      timer_ = GPT2;
      peripheral = PRCM_PERIPH_TIMER2;
      interrupt = INT_GPT2A;
      break;
    case Id::kTimer3:
      timer_ = GPT3;
      peripheral = PRCM_PERIPH_TIMER3;
      interrupt = INT_GPT3A;
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

  timer_->TAMR.TAILD = 1;  // Load timeout value at next timeout instead of immediately.
  timer_->TAMR.TAMR = 0x2;  // Periodic mode.
  timer_->IMR.TATOIM = 1;  // Enable timer time out interrupt.

  IntPrioritySet(interrupt, interrupt::DriverLibPriorityLevel(priority));
  IntEnable(interrupt);
}

void PeriodicTimer::Reset() {
  timer_->CTL.raw = 0;
  timer_->CFG.raw = 0;
  timer_->TAMR.raw = 0;
  timer_->TBMR.raw = 0;
  timer_->IMR.raw = 0;
  timer_->ICLR.raw = 0xFFFFFFFF;
}

void PeriodicTimer::SetPeriod(uint32_t period_us) {
  // Assumes GPT clock is greater than and a multiple of 1MHz.
  const uint32_t cycles_per_us = clock::GetGptClockHz() / 1'000'000;
  timer_->TAILR.TAILR = cycles_per_us * period_us;
}

void PeriodicTimer::Start() {
  timer_->CTL.TAEN = 1;
}

void PeriodicTimer::Stop() {
  timer_->CTL.TAEN = 0;
}

void PeriodicTimer::ClearInterrupt() {
  GptIclrRegDef reg;
  reg.raw = 0;
  reg.TATOCINT = 1;
  timer_->ICLR.raw = reg.raw;
}

};  // namespace timer
