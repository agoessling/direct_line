#include "src/board.hh"

#include <array>
#include <cstdint>

#include <FreeRTOS.h>
#include <task.h>

using board::GpioPin;

static void LedTaskFunc(void * /*params*/) {
  while (true) {
    constexpr uint32_t kDelayMs = 500;
    vTaskDelay(kDelayMs);
    board::GpioToggle(GpioPin::kRedLed);
  }
}

int main() {
  board::BoardInit();

  // These must be declared static as the stack is reset below.
  static StaticTask_t led_tcb;
  constexpr size_t kLedStackSize = 200;
  static std::array<StackType_t, kLedStackSize> led_stack;
  xTaskCreateStatic(LedTaskFunc, "LED", led_stack.size(), nullptr, 1, led_stack.data(), &led_tcb);

  // Reminder: The main stack is reset in this function so local stack variables cease to exist.
  // This is why the task variables above must be declared "static".
  vTaskStartScheduler();

  return 0;
}
