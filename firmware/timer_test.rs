#![no_std]
#![no_main]
//! Test each GPT assignment with one counter and three independent interrupt timers.
mod clock;
mod ddi;
mod interrupts;
mod mmio;
mod poll;
#[expect(dead_code, reason = "this image uses GPT clocks only")]
mod prcm;
mod rtc;
mod setup;
mod startup;
mod timer;

use cc1354p10_registers as r;
use core::arch::asm;
use core::sync::atomic::{AtomicU32, Ordering};
use poll::wait_for;
use timer::{Counter, GPT_CLOCK_HZ, Instance, Timer, ticks_from_us};

// Check conversion boundaries at build time using the driver's actual clock configuration.
const _: () = {
    assert!(matches!(ticks_from_us(0), Some(0)));
    assert!(matches!(ticks_from_us(100_000), Some(4_800_000)));
    assert!(matches!(ticks_from_us(89_478_485), Some(4_294_967_280)));
    assert!(ticks_from_us(89_478_486).is_none());
    assert!(ticks_from_us(u32::MAX).is_none());
};

#[unsafe(no_mangle)]
static TIMER_INSTANCE_TEST_RESULT: AtomicU32 = AtomicU32::new(0);

#[unsafe(no_mangle)]
pub extern "C" fn main() -> ! {
    const INSTANCES: [Instance; 4] = [
        Instance::Gpt0,
        Instance::Gpt1,
        Instance::Gpt2,
        Instance::Gpt3,
    ];
    let counter_index = if cfg!(feature = "counter_gpt0") {
        0
    } else if cfg!(feature = "counter_gpt1") {
        1
    } else if cfg!(feature = "counter_gpt2") {
        2
    } else {
        assert!(cfg!(feature = "counter_gpt3"));
        3
    };

    // SAFETY: this image replaces Board initialization; startup still masks CPU interrupts.
    // Each GPT is constructed once, with one counter and the other three as timers.
    let (counter, mut timers) = unsafe {
        prcm::initialize_timer_clock();
        let mut gates = r::PRCM.gptclkgr.read().clk_en();
        let counter = Counter::initialize(INSTANCES[counter_index]);
        gates |= 1 << counter_index;
        assert_eq!(r::PRCM.gptclkgr.read().clk_en(), gates);
        assert!(r::PRCM.pdstat0.read().periph_on());
        let timers: [Timer; 3] = core::array::from_fn(|index| {
            let instance_index = (counter_index + index + 1) % 4;
            let timer = Timer::initialize(INSTANCES[instance_index]);
            // Adding a timer preserves earlier gates and the shared clock rate.
            gates |= 1 << instance_index;
            assert_eq!(r::PRCM.gptclkgr.read().clk_en(), gates);
            assert_eq!(r::PRCM.gptclkdiv.read().ratio(), 0);
            timer
        });
        // The original counter must still advance after all three other GPTs are initialized.
        let start = counter.now();
        wait_for(1_000_000, || counter.elapsed_since(start) != 0);
        (counter, timers)
    };
    let mut clocks = clock::Clocks { _private: () };
    clocks.request_hf_crystal();
    wait_for(2_000_000, || clocks.hf_crystal_ready());
    wait_for(2_000_000, || clocks.try_switch_to_hf_crystal());
    // SAFETY: timer clocks, priorities, and vectors are initialized; no timeout is armed yet.
    unsafe { interrupts::enable() };

    // All three sources must service interrupts independently while the counter advances.
    for timer in &mut timers {
        timer.start_periodic_us(1_000).unwrap();
    }
    let start = counter.now();
    wait_for(48_000_000, || {
        assert!(counter.elapsed_since(start) < GPT_CLOCK_HZ);
        timers.iter().all(|timer| timer.interrupts() >= 20)
    });

    // Invalid requests preserve an active timer; stopping one must leave the others running.
    assert!(timers[0].start_periodic_us(0).is_err());
    assert!(timers[0].start_once_us(u32::MAX).is_err());
    let before = timers[0].interrupts();
    wait_ten_ms(&counter);
    assert!(timers[0].interrupts().wrapping_sub(before) > 1);
    timers[0].stop();
    let stopped = timers[0].interrupts();
    let other_counts = [timers[1].interrupts(), timers[2].interrupts()];
    wait_ten_ms(&counter);
    assert_eq!(timers[0].interrupts(), stopped);
    for (timer, before) in timers[1..].iter().zip(other_counts) {
        assert!(timer.interrupts().wrapping_sub(before) > 1);
    }

    // Each instance must fire only once when rearmed as a one-shot.
    for timer in &mut timers {
        timer.stop();
        let before = timer.interrupts();
        timer.start_once_us(1_000).unwrap();
        wait_ten_ms(&counter);
        assert_eq!(timer.interrupts(), before.wrapping_add(1));
        timer.stop();
    }
    let stopped = timers.each_ref().map(Timer::interrupts);
    wait_ten_ms(&counter);
    assert_eq!(timers.each_ref().map(Timer::interrupts), stopped);

    TIMER_INSTANCE_TEST_RESULT.store(0x5041_5353, Ordering::Relaxed);
    loop {
        // SAFETY: tests are complete; park for debugger inspection.
        unsafe { asm!("wfi", options(nomem, nostack)) };
    }
}

fn wait_ten_ms(counter: &Counter) {
    let start = counter.now();
    let ticks = ticks_from_us(10_000).unwrap();
    wait_for(1_000_000, || counter.elapsed_since(start) >= ticks);
}
