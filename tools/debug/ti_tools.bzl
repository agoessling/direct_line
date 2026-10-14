"""Pinned Linux TI debug tools, installed inside a Bazel external repository.

Uses TI's public unmodified installer. No existing UniFlash/CCS installation,
root operation, user-installed SDK, or user-selected tool path is consulted.
See docs/hardware_tests.md for license and host-platform details.
"""

_VERSION = "9.6.0.5764"
_URL = "https://dr-download.ti.com/software-development/software-programming-tool/MD-QeJBJLj8gq/9.6.0/uniflash_sl.9.6.0.5764.run"
_SHA256 = "66e78bfa083492999c524a6ea97c16b4b90be54d65beae7701210fb6404b0d9c"
_BASE = "distribution/deskdb/content/TICloudAgent/linux/ccs_base"

_BUILD = """
load("@rules_python//python:defs.bzl", "py_library")

package(default_visibility = ["//visibility:public"])

exports_files(["VERSION.txt", "manifest.json", "{base}/cloudagent/node"])

py_library(
    name = "scripting",
    srcs = glob(["distribution/deskdb/content/TICloudAgent/linux/scripting/python/site-packages/scripting/**/*.py"]),
    data = ["distribution/deskdb/content/TICloudAgent/linux/scripting/python/site-packages/scripting/py.typed"],
    imports = ["distribution/deskdb/content/TICloudAgent/linux/scripting/python/site-packages"],
    deps = ["@python_deps//websockets"],
)

filegroup(
    name = "dslite",
    srcs = ["{base}/DebugServer/bin/DSLite"],
)

filegroup(
    name = "licenses",
    srcs = glob(["distribution/docs/licenses/**", "distribution/docs/mainfests/**"]),
)

# Keep TI's directory structure intact: native libraries, dynamically loaded
# drivers, XML target descriptions, GEL includes, and CloudAgent modules resolve
# relative to one another. The desktop GUI is not needed.
filegroup(
    name = "runtime",
    srcs = ["VERSION.txt", "manifest.json", ":licenses"] + glob([
        "{base}/DebugServer/bin/**",
        "{base}/DebugServer/components/**",
        "{base}/DebugServer/ca-modules/**",
        "{base}/DebugServer/drivers/**",
        "{base}/DebugServer/flashDB/**",
        "{base}/DebugServer/packages/**",
        "{base}/DebugServer/propertyDB/**",
        "{base}/DebugServer/schemas/**",
        "{base}/DebugServer/scripts/**",
        "{base}/common/bin/**",
        "{base}/common/targetdb/**",
        "{base}/common/uscif/**",
        "{base}/emulation/**",
        "{base}/cloudagent/**",
    ]),
)
"""

def _ti_debug_tools_impl(ctx):
    if ctx.os.name != "linux" or ctx.os.arch not in ["amd64", "x86_64"]:
        fail("Pinned TI debug tools currently support Linux x86_64 only")

    identity = ctx.execute(["/usr/bin/id", "-u"], quiet = True)
    if identity.return_code or not identity.stdout.strip():
        fail("Cannot determine the effective user ID before running the TI installer")
    if identity.stdout.strip() == "0":
        fail("Run Bazel as an unprivileged user: the TI installer changes system USB configuration when run as root")

    ctx.report_progress("Downloading TI UniFlash " + _VERSION)
    ctx.download(
        url = _URL,
        output = "installer.run",
        sha256 = _SHA256,
        executable = True,
        canonical_id = "ti-uniflash-" + _VERSION + "-linux-x86_64",
    )
    ctx.file("install_tmp/.keep", "")
    ctx.report_progress("Installing TI command-line tools into the external repository")
    result = ctx.execute(
        [
            str(ctx.path("installer.run")),
            "--mode",
            "unattended",
            "--unattendedmodeui",
            "none",
            "--prefix",
            str(ctx.path("distribution")),
        ],
        timeout = 300,
        # BitRock 9.6 crashes while creating temp files with a long absolute
        # TMPDIR (as found in Bazel output bases). A short relative path keeps
        # installer scratch files inside this repository and avoids that bug.
        environment = {"TMPDIR": "install_tmp"},
        quiet = True,
    )
    if result.return_code:
        fail("TI UniFlash installation failed ({}):\n{}\n{}".format(
            result.return_code,
            result.stdout,
            result.stderr,
        ))

    # Check the distribution shape before publishing targets; a successful
    # installer exit alone does not establish that every required tool exists.
    required = [
        _BASE + "/DebugServer/bin/DSLite",
        _BASE + "/common/uscif/xds110/xds110reset",
        _BASE + "/DebugServer/ca-modules/ds/index.js",
        "distribution/TICloudAgentHostApp/node",
        "distribution/TICloudAgentHostApp/src/main.js",
        "distribution/deskdb/content/TICloudAgent/linux/scripting/python/site-packages/scripting/__init__.py",
        _BASE + "/common/targetdb/devices/cc1354p10.xml",
        _BASE + "/emulation/gel/cc26x4.gel",
        "distribution/docs/licenses/license.txt",
        "distribution/docs/mainfests/Uniflash_9.6.0_manifest.html",
    ]
    for path in required:
        if not ctx.path(path).exists:
            fail("TI installer did not produce required runtime file: " + path)

    # CCS Scripting expects CloudAgent beside DebugServer; UniFlash ships it separately.
    ctx.symlink(ctx.path("distribution/TICloudAgentHostApp"), _BASE + "/cloudagent")
    ctx.file("VERSION.txt", "TI UniFlash " + _VERSION + "\n")
    ctx.file("manifest.json", json.encode_indent({
        "product": "TI UniFlash",
        "version": _VERSION,
        "platform": "linux-x86_64",
        "installer_url": _URL,
        "installer_sha256": _SHA256,
        "license": "distribution/docs/licenses/license.txt",
        "software_manifest": "distribution/docs/mainfests/Uniflash_9.6.0_manifest.html",
    }) + "\n")
    ctx.file("BUILD.bazel", _BUILD.format(base = _BASE))
    ctx.delete("installer.run")
    ctx.delete("install_tmp")

ti_debug_tools = repository_rule(
    implementation = _ti_debug_tools_impl,
    doc = "Fetch and install pinned TI UniFlash command-line tools for Linux x86_64.",
)
