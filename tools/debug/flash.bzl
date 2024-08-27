def flash_target(name, ccxml, binary, **kwargs):
    native.sh_binary(
        name = name,
        srcs = ["@//tools/debug:dslite_wrapper.sh"],
        data = [ccxml, binary],
        args = [
            "flash",
            "--config",
            "$(rootpath {})".format(ccxml),
            "$(rootpath {})".format(binary),
        ],
        **kwargs
    )
