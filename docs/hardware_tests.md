# Running the primitive tests on a LaunchPad

`//src:hardware_test` is a separate firmware image for the CC1354P10. It replaces
the application in flash and reports results over the XDS110 application UART
at 115200 baud, 8N1. It does not exercise the radio.

Build it with the repository's downloaded ARM toolchain:

```sh
bazel build --config=m33 //src:hardware_test
```

The firmware checks:

- Pool exhaustion, distinct allocations, reuse, and construction/destruction.
- Queue capacity, FIFO order, retained payload lifetime, and cleanup.
- Empty and mixed-type argument storage and deferred formatting.
- MPSC operation with two FreeRTOS task producers, a priority-0 timer interrupt
  producer, and one consumer. Each producer must deliver 10,000 records. The
  consumer checks per-producer sequence numbers and payload checksums.

Full queues cause retries; the ISR retries on a later timer interrupt and never
waits for the consumer. Task producers yield so that a delayed publication can
finish. The test prints retry counts and task stack high-water marks. A task
watchdog reports stalls after 15 seconds; the host timeout also covers faults or
stuck interrupts that prevent the watchdog from running.

The final success marker is:

```text
RESULT PASS 30000 ordered/checksummed records
```

This is a functional stress test using the production ARM allocator. A passing
run does not prove every interrupt interleaving, resolve the pool's C++ object
lifetime concern described in [the review](lock_free_primitives.md), or establish
a performance advantage over another implementation. Timing includes deliberate
task delays and UART reporting; it is not a throughput benchmark.

## Host setup

Install [TI UniFlash](https://www.ti.com/tool/download/UNIFLASH). Its `DSLite`
executable is normally under
`deskdb/content/TICloudAgent/linux/ccs_base/DebugServer/bin/` in the installation.
The test runner uses Python 3's standard library.

Both the USB probe and its serial device must be writable by the current user.
Inspect `lsusb` and `/dev/serial/by-id/` to identify them. A temporary ACL can
grant access to the specific device nodes; unplugging a board or updating its
probe firmware recreates those nodes and removes the ACL.

For persistent access on this Ubuntu host, install the checked-in rules once:

```sh
sudo install -m 0644 tools/debug/60-direct-line-xds110.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=usb
sudo udevadm trigger --action=add --subsystem-match=tty
sudo udevadm settle
```

The rules grant access to `plugdev`, which this account already belongs to, and
to the active local desktop user through `uaccess`. They match the two probe
serial numbers below, regardless of USB port or assigned device number. They
also cover TI ROM DFU identity `1cbe:00ff`: XDS110 firmware updates use this mode
without a USB serial-number attribute. That rule also applies to other TI
Stellaris ROM DFU devices. Add another serial-specific pair of rules when adding
a new board. No login-session restart is needed for this account.

The two probes connected on 2026-10-01 enumerated as:

| XDS110 serial | Application UART at discovery |
| --- | --- |
| `LS4500Q0` | `/dev/ttyACM1` |
| `LS4500IY` | `/dev/ttyACM3` |

Use probe serial numbers rather than relying on those changing `ttyACM` numbers.
The USB product string says CC1352R1; it is insufficient to identify the target
silicon. The runner checks the CC13x4/CC26x4 factory identity registers against
TI's `ChipInfo_GetChipType()` decoding before writing flash.

On this host, compile the optional shutdown workaround described below first:

```sh
cc -shared -fPIC tools/debug/dslite_exit_compat.c -o /tmp/dslite_exit_compat.so
python3 tools/debug/hardware_test.py \
  --dslite "$HOME/ti/uniflash_9.6.0/deskdb/content/TICloudAgent/linux/ccs_base/DebugServer/bin/DSLite" \
  --exit-compat-library /tmp/dslite_exit_compat.so \
  --probe LS4500Q0 --output-dir /tmp/direct-line-test-LS4500Q0
```

Repeat with `LS4500IY` and a different output directory for the second board.
The runner requires an explicit probe serial, opens its application UART before
starting the firmware, verifies the flashed image, and saves the output. After
flashing, it holds the MCU in reset, clears old UART data, starts capture, and
releases reset. This prevents output from an earlier run from supplying a false
PASS. Check its exit status as well as the UART log.

The firmware remains on the board after the test. Resetting runs it again.

## Hardware results, 2026-10-01

Both connected targets were identified as **CC1354P10**, with `USER_ID=0x1287f000`
and `ICEPICK_ID=0x1bb7802f`. Both XDS110 probes now run firmware 3.0.0.43.
The installed udev rules preserved access through their USB re-enumeration.

| Probe | Flash verification | Pool / queue / storage checks | MPSC after hardware reset |
| --- | --- | --- | --- |
| `LS4500Q0` | Passed | Passed | 30,000 ordered, checksummed records |
| `LS4500IY` | Passed | Passed | 30,000 ordered, checksummed records |

Each producer delivered exactly 10,000 records. In the final reset-based runs,
queue-full retries were 0, 509, and 5,608 for task 0, task 1, and the ISR,
respectively. These are full-queue retries, not failed exclusive-store counts.
Both tests reported 1,578 elapsed RTOS ticks. The consumer's minimum untouched
stack was 1,236 words out of 1,536; each producer retained 480 out of 512 words.
Those are workload-specific high-water observations, not worst-case bounds.

The normal application initially printed its startup line and then stopped
logging. Its task had only 200 words (800 bytes) of stack. Inspection of the ARM
ELF showed 816 bytes of nested integer-formatting frames, before exception and
scheduler context. Increasing the task allocation to 512 words (2 KiB) restored
sustained timer logging on both boards after hardware reset. Both passed an
8-second smoke capture with a startup message and 77 increasing timer records.
The normal application was flashed again after the primitive tests.
An attach-without-reset snapshot of the first board's task stack found 308
untouched words out of 512, corresponding to an observed peak of 816 bytes.
That supports the diagnosis and confirms headroom for this workload; it does not
bound every possible formatter input or interrupt schedule.

The ARM application and hardware-test image build successfully, and all three
host test targets pass. The UART and flash-verification logs are saved beside
this document under `hardware_results/2026-10-01/`, with firmware hashes and
identity information in the [manifest](hardware_results/2026-10-01/manifest.txt).

## Host-tool compatibility

UniFlash 9.6.0 and 8.8.0 exhibit a shutdown hang on this Ubuntu 26.04 host:
`DSLite memory --help` prints its output but does not exit. Investigation found
a worker thread entering `exit()` and waiting in condition-variable destruction
while another thread is still waiting on that variable.

`dslite_exit_compat.c` is an optional workaround for that observed shutdown bug.
It preserves the requested exit status, flushes C output, and exits without
running process-wide exit handlers or destructors. The runner's
`--exit-compat-library` option loads it into DSLite only. Use it only on affected
hosts; normal installations can omit the option. Chip reads, programming,
verification, and hardware-reset boot tests succeeded using it here. A tool
failure or timeout still fails the run.

Both probe firmware transfers reported `DFU_ERR_UNKNOWN` even though the new
firmware had been written. A USB reset restored runtime enumeration, which then
reported 3.0.0.43 for each serial number. The subsequent successful debug and
flash operations confirmed probe operation. The original updater message alone
was not treated as proof of either success or failure.
