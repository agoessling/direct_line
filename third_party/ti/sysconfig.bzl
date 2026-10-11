"""Run only CCFG generation, with all tool and SDK inputs declared."""

def _ccfg_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name)
    args = ctx.actions.args()
    args.add(ctx.file._cli)
    args.add("--product", ctx.file._product)
    args.add("--board", ctx.attr.board)
    args.add_all(["--compiler", "gcc", "--rtos", "none"])
    args.add("--script", ctx.file.src)
    args.add("--output", output.path)
    args.add("--treatWarningsAsErrors")
    ctx.actions.run(
        executable = ctx.executable._node,
        arguments = [args],
        inputs = depset([ctx.file.src, ctx.file._product], transitive = [
            ctx.attr._cli_files[DefaultInfo].files,
            ctx.attr._sdk_files[DefaultInfo].files,
        ]),
        outputs = [output],
        mnemonic = "SysConfig",
        progress_message = "Generating CCFG for %s" % ctx.attr.board,
    )

    # A normal file lets cc_library track the generated C translation unit.
    source = ctx.actions.declare_file(ctx.label.name + ".c")
    ctx.actions.run_shell(
        inputs = [output],
        outputs = [source],
        arguments = [output.path + "/ti_devices_config.c", source.path],
        command = 'cp "$1" "$2"',
    )
    return [DefaultInfo(files = depset([source]))]

ccfg = rule(
    implementation = _ccfg_impl,
    attrs = {
        "board": attr.string(mandatory = True, doc = "SysConfig board identifier, such as /ti/boards/LP_EM_CC1354P10_1."),
        "src": attr.label(allow_single_file = [".syscfg"], mandatory = True),
        "_node": attr.label(default = "@ti_sysconfig//:sysconfig/nodejs/node", executable = True, allow_single_file = True, cfg = "exec"),
        "_cli": attr.label(default = "@ti_sysconfig//:sysconfig/dist/cli.js", allow_single_file = True),
        "_cli_files": attr.label(default = "@ti_sysconfig//:cli"),
        "_product": attr.label(default = "@ti_sdk//:.metadata/product.json", allow_single_file = True),
        "_sdk_files": attr.label(default = "@ti_sdk//:sysconfig_inputs"),
    },
)
