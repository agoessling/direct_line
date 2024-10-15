#include "src/board.hh"

#include <array>
#include <cstdint>

#include <FreeRTOS.h>
#include <task.h>

#include <emio/emio.hpp>
#include "src/timer.hh"
#include "src/uart.hh"

using board::GpioPin;

static void LedTaskFunc(void * /*params*/) {
  uart::Uart uart(uart::Id::kUart0);
  auto result = uart.Configure();
  if (!result) {
    while (true) {}
  }

  while (true) {
    constexpr uint32_t kDelayMs = 500;
    vTaskDelay(kDelayMs);

    emio::static_buffer<32> buffer;
    auto result = emio::format_to(buffer, "Task Delay: {:d} [ms]\r\n", kDelayMs);
    if (!result) {
      continue;
    }
    uart.Send(buffer.view());

    board::GpioToggle(GpioPin::kRedLed);
  }
}

static timer::PeriodicTimer g_timer(timer::Id::kTimer0, interrupt::Priority::kLevel0);

extern "C" {
void Timer0AHandler() {
  g_timer.ClearInterrupt();
  board::GpioToggle(GpioPin::kGreenLed);
}
}

int main() {
  board::BoardInit();

  // These must be declared static as the stack is reset below.
  static StaticTask_t led_tcb;
  constexpr size_t kLedStackSize = 200;
  static std::array<StackType_t, kLedStackSize> led_stack;
  xTaskCreateStatic(LedTaskFunc, "LED", led_stack.size(), nullptr, 1, led_stack.data(), &led_tcb);

  g_timer.SetPeriod(500'000);
  g_timer.Start();

  // Reminder: The main stack is reset in this function so local stack variables cease to exist.
  // This is why the task variables above must be declared "static".
  vTaskStartScheduler();

  return 0;
}
