"""Expose embedded build artifacts to host tests without changing their platform."""

def _m33_impl(_settings, _attr):
    return {"//command_line_option:platforms": "//tools/platforms:bare_metal_m33"}

_m33 = transition(
    implementation = _m33_impl,
    inputs = [],
    outputs = ["//command_line_option:platforms"],
)

def _artifact_impl(ctx):
    return [DefaultInfo(files = ctx.attr.target[0][DefaultInfo].files)]

m33_artifact = rule(
    implementation = _artifact_impl,
    attrs = {
        "target": attr.label(mandatory = True, cfg = _m33),
        "_allowlist_function_transition": attr.label(default = "@bazel_tools//tools/allowlists/function_transition_allowlist"),
    },
)
