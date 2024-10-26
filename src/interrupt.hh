#pragma once

#include <utility>

#include <ti/devices/cc13x4_cc26x4/driverlib/interrupt.h>

#include "src/concepts.hh"

namespace interrupt {

enum class Priority {
  kLevel0 = 0,
  kLevel1 = 1,
  kLevel2 = 2,
  kLevel3 = 3,
  kLevel4 = 4,
  kLevel5 = 5,
  kLevel6 = 6,
  kLevel7 = 7,
};

static inline uint8_t DriverLibPriorityLevel(Priority priority) {
  switch (priority) {
    case Priority::kLevel0:
      return INT_PRI_LEVEL0;
    case Priority::kLevel1:
      return INT_PRI_LEVEL1;
    case Priority::kLevel2:
      return INT_PRI_LEVEL2;
    case Priority::kLevel3:
      return INT_PRI_LEVEL3;
    case Priority::kLevel4:
      return INT_PRI_LEVEL4;
    case Priority::kLevel5:
      return INT_PRI_LEVEL5;
    case Priority::kLevel6:
      return INT_PRI_LEVEL6;
    case Priority::kLevel7:
      return INT_PRI_LEVEL7;
  }
  return INT_PRI_LEVEL7;
}

// Scope guard which enters a critical section on construction and exits on destruction.  When
// possible prefer use of the CriticalSection() function below.
class CriticalSectionGuard {
 public:
  CriticalSectionGuard() noexcept {
    asm("mrs %0, PRIMASK\n"
        "cpsid i"
        : "=r"(primask_)
        :
        : "memory");
  }

  ~CriticalSectionGuard() noexcept { asm volatile("msr PRIMASK, %0" : : "r"(primask_) : "memory"); }

  // Not copyable or moveable.
  CriticalSectionGuard(const CriticalSectionGuard&) = delete;
  CriticalSectionGuard(CriticalSectionGuard&&) = delete;
  CriticalSectionGuard& operator=(const CriticalSectionGuard&) = delete;
  CriticalSectionGuard& operator=(CriticalSectionGuard&&) = delete;

 private:
  uint32_t primask_;
};

template <NoThrowCallable F>
decltype(auto) CriticalSection(F&& func) noexcept {
  CriticalSectionGuard guard;
  return std::forward<F>(func)();
}

}  // namespace interrupt
