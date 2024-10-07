#pragma once

#include <ti/devices/cc13x4_cc26x4/driverlib/interrupt.h>

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

}  // namespace interrupt
