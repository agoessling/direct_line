#include "src/cc1354p10_reg_def.h"

int main() {
  volatile float temp1 = 1.2345f; // NOLINT(readability-magic-numbers)
  volatile float temp2 = 1.2345f * temp1; // NOLINT(readability-magic-numbers)
  (void)temp2;
  return 0;
}
