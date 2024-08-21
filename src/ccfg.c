//#####################################
// Force VDDR high setting (Higher output power but also higher power consumption)
// This is also called "boost mode"
//#####################################

// Use default VDDR trim
#define CCFG_FORCE_VDDR_HH                              0x0


//#####################################
// Power settings
//#####################################

// Use the DC/DC during recharge in powerdown
#define SET_CCFG_MODE_CONF_DCDC_RECHARGE                0x0

// Use the DC/DC during active mode
#define SET_CCFG_MODE_CONF_DCDC_ACTIVE                  0x0


//#####################################
// Clock settings
//#####################################

// LF XOSC
#define SET_CCFG_MODE_CONF_SCLK_LF_OPTION               0x2

// Don't apply cap-array delta
#define SET_CCFG_MODE_CONF_XOSC_CAP_MOD                 0x1

//#####################################
// Special HF clock source setting
//#####################################

// HF source is a 48 MHz xtal
#define SET_CCFG_MODE_CONF_XOSC_FREQ                    0x2

//#####################################
// Bootloader settings
//#####################################

// Disable ROM boot loader
#define SET_CCFG_BL_CONFIG_BOOTLOADER_ENABLE            0x00

// Default address in IMAGE_VALID_CONF register
#define SET_CCFG_IMAGE_VALID_CONF_IMAGE_VALID           0x00000000

//#####################################
// Debug access settings
//#####################################

// Disable unlocking of TI Failure Analysis option
#define SET_CCFG_CCFG_TI_OPTIONS_TI_FA_ENABLE           0x00

// Disable customer key CKEY0-3 to be XOR'ed with TI FA option unlock key
#define SET_CCFG_CCFG_TI_OPTIONS_C_FA_DIS               0xC5

// Access enabled if also enabled in FCFG
#define SET_CCFG_CCFG_TAP_DAP_0_CPU_DAP_ENABLE          0xC5

// Access enabled if also enabled in FCFG
#define SET_CCFG_CCFG_TAP_DAP_0_PWRPROF_TAP_ENABLE      0xC5

// Access disabled
#define SET_CCFG_CCFG_TAP_DAP_0_TEST_TAP_ENABLE         0x00

// Access disabled
#define SET_CCFG_CCFG_TAP_DAP_1_PBIST2_TAP_ENABLE       0x00

// Access disabled
#define SET_CCFG_CCFG_TAP_DAP_1_PBIST1_TAP_ENABLE       0x00

// Access disabled
#define SET_CCFG_CCFG_TAP_DAP_1_AON_TAP_ENABLE          0x00

//#####################################
// Select between cache or GPRAM
//#####################################

// Cache is enabled and GPRAM is disabled (unavailable)
#define SET_CCFG_SIZE_AND_DIS_FLAGS_DIS_GPRAM           0x1


// Set all of flash to non-secure, except the lowest 8 KB
#define SET_CCFG_TRUSTZONE_FLASH_CFG_NSADDR_BOUNDARY    0x1

//#####################################
// Bus security settings
//#####################################

// NOLINTNEXTLINE(bugprone-suspicious-include)
#include <ti/devices/cc13x4_cc26x4/startup_files/ccfg.c>
