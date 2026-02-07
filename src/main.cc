#include "src/board.hh"

#include <array>
#include <cstdint>

#include <FreeRTOS.h>
#include <task.h>

#include <emio/emio.hpp>
#include "src/console_log.hh"
#include "src/timer.hh"
#include "src/uart.hh"

using board::GpioPin;

std::terminate_handler __terminate_handler = nullptr;

static timer::PeriodicTimer g_timer(timer::Id::kTimer0, interrupt::Priority::kLevel0);
static timer::WrappingTimer g_clock(timer::Id::kTimer1);
static console_log::ConsoleLogger g_logger(g_clock);

static void LedTaskFunc(void * /*params*/) {
  uart::Uart uart(uart::Id::kUart0);
  auto result = uart.Configure();
  if (!result) {
    while (true) {}
  }

  while (true) {
    constexpr uint32_t kDelayMs = 500;
    vTaskDelay(kDelayMs);

    board::GpioToggle(GpioPin::kRedLed);

    while (true) {
      emio::static_buffer<64> buffer;
      const emio::result<void> result = g_logger.ProcessOne(buffer);
      if (result.has_error()) {
        uart.Send(emio::to_string(result.assume_error()));
        uart.Send("\r\n");
        continue;
      }
      if (buffer.view().size() == 0) {
        break;
      }
      uart.Send(buffer.view());
    }
  }
}

extern "C" {
void Timer0AHandler() {
  g_timer.ClearInterrupt();
  board::GpioToggle(GpioPin::kGreenLed);
  g_logger.Log("Timer interrupt: {:d}", g_clock.Now());
}
}

int main() {
  board::BoardInit();

  // These must be declared static as the stack is reset below.
  static StaticTask_t led_tcb;
  constexpr size_t kLedStackSize = 200;
  static std::array<StackType_t, kLedStackSize> led_stack;
  xTaskCreateStatic(LedTaskFunc, "LED", led_stack.size(), nullptr, 1, led_stack.data(), &led_tcb);

  g_timer.SetPeriod(100'000);
  g_timer.Start();
  g_clock.Start();

  // Reminder: The main stack is reset in this function so local stack variables cease to exist.
  // This is why the task variables above must be declared "static".
  vTaskStartScheduler();

  return 0;
}
