def freertos_port(name, port_path, **kwargs):
    if not port_path.endswith("/"):
        port_path += "/"

    native.cc_library(
        name = name + "_include",
        hdrs = native.glob([port_path + "*.h"], allow_empty = False),
        includes = [port_path],
        **kwargs
    )

    native.filegroup(
        name = name + "_source",
        srcs = (
            native.glob([port_path + "*.c"], allow_empty = False) +
            native.glob([port_path + "*.S"], allow_empty = True)
        ),
        **kwargs
    )

def freertos_library(name, port, freertos_config_lib, heap = None, **kwargs):
    """ Creates FreeRTOS library specific to project.

    Args:
      name: Name used for the cc_library.
      port: Name of port (see freertos.BUILD).
      freertos_config_lib: Library which exposes "FreeRTOSConfig.h" and can be imported without
          prefix (e.g. #include "FreeRTOSConfig.h") from external libraries.
      heap: Name of FreeRTOS heap manager to use (e.g. "heap_4") or None.
    """
    if heap == None:
        heap_srcs = []
    else:
        heap_srcs = ["@freertos//:{}".format(heap)]

    native.cc_library(
        name = name,
        srcs = [
            "@freertos_kernel//:common_source",
            "@freertos_kernel//:{}_source".format(port),
        ] + heap_srcs,
        deps = [
            freertos_config_lib,
            "@freertos_kernel//:common_include",
            "@freertos_kernel//:{}_include".format(port),
        ],
        alwayslink = True,
        **kwargs
    )
