# Digital Discovery UART latency fixture

## Status and purpose

**2026-10-23: the user ordered a Digilent Digital Discovery. Hardware integration is planned, not
implemented or verified.** This document captures the agreed measurement direction and the research
needed to resume when it arrives. It refers to Digital Discovery, not Analog Discovery or ADP2230.

The application is a transparent, low-latency UART link between two LP-EM-CC1354P10-1 boards. Bytes
must emerge in order on the corresponding channel; application framing and preservation of interbyte
gaps are not required. The eventual maximum is four full-duplex UART channels, up to the MCU's
documented 3 Mbaud, using 8N1. This is a fixture capacity target, not a claim that the RF link can
sustain all channels at maximum rate simultaneously. RF throughput and overload policy remain open.

The fixture should drive known traffic and observe the actual input and output wires on one
timebase. This provides end-to-end latency and corruption/loss measurements without synchronizing
the MCU clocks. Internal MCU and RF timestamps can later explain where latency occurs; they are not
needed for this external reference measurement. The user also owns a Saleae Logic 8 for independent
checks.

Two-second acquisitions were the original requirement. Longer acquisitions are useful, but
continuous unlimited streaming is not an established Digital Discovery capability at our desired
sample rates. Prefer automated finite runs with download/analysis between them over assuming gapless
USB streaming.

## Wiring and UART ownership

For four full-duplex links, the fixture needs **eight generated streams and sixteen captured
wires**:

| Discovery signals, proposed | Connection | Capture purpose |
| --- | --- | --- |
| DIO24–27, outputs | Board A UART0–3 RX | Observe traffic entering A |
| DIO28–31, outputs | Board B UART0–3 RX | Observe traffic entering B |
| DIO32–35, inputs | Board A UART0–3 TX | Observe traffic leaving A |
| DIO36–39, inputs | Board B UART0–3 TX | Observe traffic leaving B |

This arrangement permits packed 16-bit, DIO-first acquisition. Confirm SDK bit order with a walking
signal before interpreting captures. RX/TX above are named from the MCU's perspective. A stimulus
entering A channel N is compared with the output from B channel N, and conversely.

Use 3.3 V logic and common grounds, with short leads and nearby ground returns. The Discovery can
observe its driven DIOs, but that readback is not an independent measurement at the receiving MCU
pad. Use the Saleae or a separate input tap to check the physical wiring during qualification.

The MCU's IOC can route all four UART RX/TX pairs to available digital GPIOs; DIO12/13 are board
defaults, not mandatory UART pins. Select and document eight otherwise-unused header GPIOs on each
board after checking the schematic. Avoid DIO12/13, which also connect to the XDS110 UART bridge,
and pins occupied by debug, LEDs, buttons, or RF controls. Keep JTAG and board power connected. If
DIO12/13 are used instead, isolate the debugger UART connection to avoid competing output drivers.
The USB UART bridge is separate from JTAG itself.

The board design uses 2.54 mm stacking sockets on the bottom with male tails exposed on top.
Female-ended leads can attach to the top. Verify orientation against the board labels; header pin
numbers and MCU DIO numbers are different. No final eight-pin MCU assignment has been selected.

Current software limitations:

- `firmware/device.rs` constructs only UART0, on DIO12/13. The fixture needs an explicit board/test
  configuration owning all required UARTs and pins; do not bypass peripheral ownership.
- `firmware/uart.rs` supports UART0–3 but currently provides polling I/O, not a proven sustained
  four-channel 3-Mbaud transport. Interrupt/DMA support is separate work driven by measured needs.
- `firmware/ioc.rs` currently restricts access to DIO0–31. Choose available pins in that range
  unless extending the helper is necessary; this is a software restriction, not the MCU routing
  limit.
- Existing UART HIL cases exercise internal loopback, one instance at a time, on the same pin pair.
  They do not establish external wiring, baud accuracy, or simultaneous throughput.

## Generation and acquisition modes

### Initial qualification: ordinary custom patterns

Each output has a 32,768-sample custom buffer that repeats in hardware while running. At one sample
per UART bit, serialize each byte as a low start bit, eight LSB-first data bits, and a high stop
bit. There is no host refill at a pattern boundary.

| Payload repeated per output | Pattern samples | Period at 3 Mbaud | Fits custom buffer? |
| --- | ---: | ---: | --- |
| Bytes 0–255 | 2,560 | 0.853 ms | Yes |
| Counter 0–1023, two bytes per value | 20,480 | 6.827 ms | Yes |
| Counter 0–65535, two bytes per value | 1,310,720 | 436.907 ms | No |

Use this mode to establish generation, capture, and decoding before introducing shared DDR playback.
It leaves the DDR available for capture and is the fallback if the more flexible mode proves
fragile. Configure continuous custom-buffer repetition, not repeated host commands to restart
generation.

### Intended experiment mode: one preloaded DDR waveform

Digital Discovery Play mode supports packed patterns in DDR and simultaneous acquisition. Playback
occupies the end of DDR; acquisition starts at the beginning. The vendor warns that acquisition can
overwrite playback and corrupt generated traffic. Explicitly budget disjoint regions for the run;
do not rely on safely reclaiming already-played data.

Pre-expand the entire finite experiment into one waveform. For eight output signals, each sample is
one byte describing all eight pins, updated at 3 MHz. This costs 3 MB per second of stimulus,
including UART framing. The full counter sequence can repeat within the uploaded data without
restarting the playback engine. Deliberate idle intervals and different patterns per channel can be
encoded too.

The vendor reports cache-refill problems when restarting partial-DDR loops, sometimes requiring an
approximately 1 microsecond wait. A single finite playback avoids that restart boundary; verify its
start and end behavior rather than treating it as proven. Do not fill all DDR for seamless playback
and then expect the same memory to remain available for capture.

A nominal 96 MHz Discovery clock would permit 3-Mbaud generation and 6/12/24/48 MS/s capture through
integer division. Adjustable system clock support is documented, but this exact configuration has
not been tested. Query actual configured frequencies and verify them externally. Do not silently
substitute 100 MHz / 33 = 3.0303 Mbaud for a requested 3 Mbaud.

## Memory budget and sampling tradeoff

Digital Discovery has 256 MiB of capture/playback DDR. With eight generated outputs, sixteen
captured signals, noise capture disabled, no compression, and equal playback/capture duration:

```text
M = 256 * 1024 * 1024 bytes
generation rate = 3,000,000 samples/s * 1 byte/sample
capture rate = f_capture * 2 bytes/sample
maximum duration = M / (3,000,000 + 2 * f_capture)
```

| Samples per 3-Mbaud bit | Capture rate | Sample spacing | Calculated maximum duration |
| ---: | ---: | ---: | ---: |
| 1 | 3 MS/s | 333.3 ns | 29.83 s |
| 2 | 6 MS/s | 166.7 ns | 17.90 s |
| 4 | 12 MS/s | 83.3 ns | 9.94 s |
| 8 | 24 MS/s | 41.7 ns | 5.26 s |
| 16 | 48 MS/s | 20.8 ns | 2.71 s |

These are capacity calculations, not measured device limits or accepted SDK configurations. Reserve
margin for alignment, acquisition timing, and a trailing interval after stimulus ends. Query
capacities and reject configurations that cannot fit. For ordinary custom patterns, omit the DDR
generation term.

Start with about two seconds at 48 MS/s as the reference. Then qualify about nine seconds at 12 MS/s
and potentially seventeen seconds at 6 MS/s. An offline decoder need not imitate a UART's 16x
receiver oversampling, but lower-rate decoding must agree with reference captures across phases and
baud offsets. One sample per bit is a theoretical capacity row, not the proposed correctness
reference.

Discovery generation and acquisition share a clock; MCU transmissions do not. Equal nominal baud
does not establish equal frequency or phase, and each MCU burst can start at an arbitrary phase.
Do not assume exact clock matching when decoding returned traffic. Timestamp sample spacing is not
absolute timing accuracy: account for edge quantization, timebase error, and channel/path skew.

Continuous host streaming is optional future investigation. At sixteen bits per sample, 6 and 12
MS/s require 12 and 24 MB/s respectively; plausible USB bandwidth alone does not establish device
support. Require measured sustained operation and zero reported loss/corruption before claiming it.
Compression is not part of the baseline budget; independently timed UART traffic may compress
poorly.

## Measurement and host implementation

Use the WaveForms SDK's packed sample interface rather than exporting decoded bytes through a GUI.
Candidate calls include `FDwfDigitalInInputOrderSet`, `FDwfDigitalInSampleFormatSet`,
`FDwfDigitalInStatusData`, and `FDwfDigitalInStatusData2`; confirm their contracts in the installed,
pinned SDK. For Record mode, `FDwfDigitalInStatusRecord` exposes available/lost/corrupt counts.
Check all relevant completion/overflow statuses and expected sample counts in whichever mode is
used.

The default latency endpoint is the corresponding byte's input start-bit edge to output start-bit
edge. Decode both observed wires; do not substitute scheduled generation time or USB write time for
the observed input edge. If adding complete-byte or burst-level latency, name those endpoints
explicitly.

Use a known two-byte counter sequence with explicit byte order, initially little-endian. Channel
patterns should distinguish misrouting, rather than relying only on identical data on all channels.
The full counter still repeats every 436.907 ms at saturation. Alignment must detect insertions,
deletions, and corruption and report ambiguity when repeated data permits multiple matches; do not
silently match modulo the sequence length or assume a maximum latency without declaring it.

Implement a narrow runner with these responsibilities:

1. Select explicit Discovery and board identities; record firmware hashes and instrument/SDK
   versions.
2. Configure the fixture and board firmware, arm capture before traffic, and execute one bounded
   run.
3. Stop generation, preserve a drain interval, download packed data, and check acquisition
   integrity.
4. Decode and align streams; report counts, framing errors, drops, insertions, corruption, and
   latency percentiles/maxima per channel and direction. Retain unmatched bytes and capture-boundary
   exclusions.
5. Save machine-readable results, configuration, and useful raw captures under ignored `.results/`.

Keep host runtime and download time separate from measured wire latency. Missing data or an
incomplete capture cannot count as a passing measurement. Retain raw samples for initial
qualification and errors; record any later retention policy. Never check raw captures into Git.

Bazel remains authoritative. Add explicit uncached hardware execution targets, pinned SDK/runtime
dependencies where distribution permits, host tests, and the existing Python typing/lint checks if
Python is used. Confirm Linux SDK dependencies and licensing before choosing packaging; document any
unavoidable workstation setup. Keep editor configuration outside this repository. A typed Python SDK
binding is a reasonable starting point; profile decoding before adding compiled processing code.

Reuse probe-rs for loading firmware and existing HIL for driver regression checks. Do not restore
the retired CCS/custom mailbox harness. During timed traffic, avoid debugger halts, semihosting, or
other measurement-induced stalls. A dedicated freely running fixture image may be more appropriate
than making the entire experiment one embedded-test case. Choose after the first hardware trial.

## Bring-up sequence and acceptance

1. **Instrument only:** identify the device, pin SDK/runtime versions, verify permissions, voltage,
   channel order, actual rates, and idle-high UART output. Capture known patterns and independently
   inspect representative signals with the Saleae. No MCU or RF dependency is needed for this stage.
2. **Ordinary patterns:** verify gapless repeats on all eight outputs and simultaneous
   sixteen-signal acquisition. Test decoder framing, chunk boundaries, clock offsets, and
   deliberately damaged data on the host. Include sequence wrap and ambiguous alignment cases.
3. **DDR Play:** reproduce one-shot playback plus acquisition. Check both ends of the waveform,
   expected sample counts, non-overlapping memory, and known byte sequences. Start well below
   capacity.
4. **One board:** select and publish the exact pin map, retain JTAG access, then test external UART
   traffic one peripheral at a time. Add concurrent channels only as firmware throughput permits.
5. **Sampling qualification:** compare low-rate decoding and latency estimates with higher-rate
   references across start phases, patterns, and baud offsets. Record uncertainty and accepted
   rates.
6. **Two-board RF:** once RF transport exists, exercise each direction and channel, then concurrent
   traffic. Vary offered load and distinguish RF overload from instrument or UART capture failures.

The first milestone is a reproducible instrument-only generation/capture command and trustworthy
decoder, followed by external UART validation. It does not depend on finishing RF or DMA first.
Record actual commands, wiring, achieved rates, capture limits, measurement uncertainty, and concise
results here as they are verified. No Digital Discovery commands or measurements exist yet.

## Source material

- [Digital Discovery hardware and buffer specifications][hardware]
- [WaveForms custom patterns and repetition][patterns]
- [Digital Discovery DDR Play and shared-memory behavior][play]
- [DDR playback restart/cache limitation][restart]
- [Adjustable Digital Discovery system clock][clock]
- [WaveForms acquisition modes][logic]
- [WaveForms SDK reference][sdk] (accessible older manual; confirm against the installed SDK)
- [CC1354P10 datasheet][mcu], section 9.8: UART limits and IOC routing
- [LaunchPad header pinout][pinout] and [board design files][design]
- [Existing HIL workflow](hardware_tests.md)

[hardware]: https://files.digilent.com/manuals/WaveForms/3.25.1/start4.html
[patterns]: https://files.digilent.com/manuals/WaveForms/3.25.1/patterns.html
[play]: https://forum.digilent.com/topic/22652-digital-discovery-play-mode/
[restart]: https://forum.digilent.com/topic/29925-when-using-fdwfdigitaloutplaydataset-with-large-sample-values-results-in-corrupted-signals/
[clock]: https://forum.digilent.com/topic/18720-external-reference-clock-for-digital-discovery/
[logic]: https://files.digilent.com/manuals/WaveForms/3.25.1/logic.html
[sdk]: https://digilent.com/reference/_media/reference/software/waveforms/waveforms-sdk/waveformssdk_reference_manual.pdf
[mcu]: https://www.ti.com/lit/ds/symlink/cc1354p10.pdf
[pinout]: https://www.ti.com/lit/ml/spruiz8/spruiz8.pdf
[design]: https://www.ti.com/tool/download/SPRR484
