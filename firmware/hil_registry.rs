//! One declaration generates ELF discovery metadata and the corresponding test functions.

pub struct TestContext {
    pub boot_rtc_seconds: u32,
}

// Shared debugger ABI; keep values in sync with tools/debug/protocol.py.
#[repr(u32)]
pub enum ExpectedOutcome {
    Pass = 0,
    Panic = 1,
    Fault = 2, // UDF UsageFault.
    Timeout = 3,
}

/// Fixed little-endian debugger ABI; text is ASCII padded with zero bytes.
#[repr(C)]
pub struct TestDescription {
    pub id: u32,
    timeout_ms: u32,
    expected: ExpectedOutcome,
    name: [u8; 52],
    suites: [u8; 64], // Space-separated names; selection happens on the host.
}

impl TestDescription {
    pub const fn new(name: &str, suites: &str, timeout_ms: u32, expected: ExpectedOutcome) -> Self {
        assert!(timeout_ms > 0 && timeout_ms <= 60_000);
        Self {
            id: 0, // Assigned from declaration order by hil_tests!.
            timeout_ms,
            expected,
            name: text(name),
            suites: text(suites),
        }
    }
}

const fn text<const N: usize>(value: &str) -> [u8; N] {
    assert!(!value.is_empty() && value.len() < N);
    let mut bytes = [0; N];
    let mut index = 0;
    while index < value.len() {
        let byte = value.as_bytes()[index];
        assert!(byte > 0 && byte.is_ascii());
        bytes[index] = byte;
        index += 1;
    }
    bytes
}

const _: () = assert!(core::mem::size_of::<TestDescription>() == 128);

macro_rules! hil_tests {
    ($($name:literal => {
        run: $run:expr,
        suites: [$($suite:ident),+ $(,)?],
        timeout_ms: $timeout:expr,
        $(expect: $expected:ident,)?
    }),+ $(,)?) => {
        const CASE_COUNT: usize = [$($name),+].len();
        const _: () = assert!(CASE_COUNT <= 256);

        #[unsafe(no_mangle)]
        pub static HIL_TESTS: [$crate::hil_registry::TestDescription; CASE_COUNT] = {
            let mut cases = [$(
                $crate::hil_registry::TestDescription::new(
                    $name,
                    concat!($(stringify!($suite), " "),+),
                    $timeout,
                    $crate::hil_registry::hil_tests!(@expected $($expected)?),
                )
            ),+];
            let mut index = 0;
            while index < cases.len() {
                cases[index].id = index as u32;
                index += 1;
            }
            cases
        };

        #[unsafe(no_mangle)]
        pub static HIL_TEST_COUNT: u32 = CASE_COUNT as u32;

        static TEST_FUNCTIONS: [fn(&$crate::hil_registry::TestContext); CASE_COUNT] = [$($run),+];
    };
    (@expected) => { $crate::hil_registry::ExpectedOutcome::Pass };
    (@expected $expected:ident) => { $crate::hil_registry::ExpectedOutcome::$expected };
}

pub(crate) use hil_tests;
