load("@arm_none_eabi//toolchain:toolchain.bzl", "arm_none_eabi_toolchain")

arm_none_eabi_toolchain(
    name = "arm_none_eabi_cortex_m33_toolchain",
    copts = [
        "-O2",
        "-mcpu=cortex-m33",
        "-mthumb",
        "-mfloat-abi=hard",
        "-mfpu=fpv5-sp-d16",
        "-nostartfiles",
        "-fno-exceptions",
        "-specs=nano.specs",
        "-g",
    ],
    linkopts = [
        "-O2",
        "-mcpu=cortex-m33",
        "-mthumb",
        "-mfloat-abi=hard",
        "-mfpu=fpv5-sp-d16",
        "-nostartfiles",
        "-fno-exceptions",
        "-specs=nano.specs",
        "-g",
    ],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
)
