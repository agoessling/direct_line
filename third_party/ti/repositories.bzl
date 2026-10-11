"""Pinned TI code-generation tool; no workstation installation or host Node."""

def _sysconfig_impl(ctx):
    if ctx.os.name != "linux" or ctx.os.arch not in ["amd64", "x86_64"]:
        fail("SysConfig currently supports Linux x86_64 build hosts only")
    ctx.download(
        url = "https://dr-download.ti.com/software-development/ide-configuration-compiler-or-debugger/MD-nsUM6f7Vvb/1.28.1.4785/sysconfig-1.28.1_4785-setup.run",
        output = "installer.run",
        sha256 = "b913ca843bf0dff177dc4c22dee2e73b9bdc129272c00a64033e3e7ee0e9f55b",
        executable = True,
    )
    result = ctx.execute([
        str(ctx.path("installer.run")),
        "--mode",
        "unattended",
        "--prefix",
        str(ctx.path("sysconfig")),
    ], timeout = 300)
    if result.return_code:
        fail("SysConfig installation failed: " + result.stdout + result.stderr)
    ctx.delete("installer.run")
    ctx.file("BUILD.bazel", """
package(default_visibility = ["//visibility:public"])
exports_files(["sysconfig/nodejs/node", "sysconfig/dist/cli.js"])
filegroup(name = "cli", srcs = glob(["sysconfig/dist/**"]))
""")

sysconfig_repository = repository_rule(implementation = _sysconfig_impl)
