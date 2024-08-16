#include "src/power_clock.hh"

#include "src/cc1354p10_reg_def.h"

void PowerControlInit() {
  // Enable DCDC
  const AonPmctlPwrctlRegDef pwr_ctl_reg = {.DCDC_EN = 1, .DCDC_ACTIVE = 1};
  AON_PMCTL->PWRCTL.raw = pwr_ctl_reg.raw;
}
