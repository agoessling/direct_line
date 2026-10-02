#include "src/board.hh"

#include <array>
#include <atomic>
#include <cstdint>
#include <string_view>
#include <tuple>

#include <FreeRTOS.h>
#include <task.h>

#include <emio/emio.hpp>
#include "src/log_entry.hh"
#include "src/memory_pool.hh"
#include "src/mpsc_queue.hh"
#include "src/storage.hh"
#include "src/timer.hh"
#include "src/uart.hh"

namespace {

// This exercises the production ARM pool, not the host-test replacement. It is a stress test,
// not a proof that every exclusive-monitor or interrupted-publication interleaving is safe.
constexpr uint32_t kProducerCount = 3;
constexpr uint32_t kRecordsPerProducer = 10'000;
constexpr uint32_t kIsrProducer = 2;
constexpr uint32_t kTimeoutMs = 15'000;

struct Record {
  uint32_t producer;
  uint32_t sequence;
  uint32_t checksum;
};

constexpr uint32_t Checksum(uint32_t producer, uint32_t sequence) {
  return (sequence * 0x9e3779b9U) ^ (producer * 0x85ebca6bU) ^ 0xa55a1234U;
}

timer::PeriodicTimer g_timer(timer::Id::kTimer0, interrupt::Priority::kLevel0);
MpscQueue<Record, 32> g_queue;
std::array<std::atomic<uint32_t>, kProducerCount> g_accepted{};
std::array<std::atomic<uint32_t>, kProducerCount> g_full{};
std::atomic<bool> g_started{false};
std::atomic<bool> g_finished{false};
uart::Uart *g_uart = nullptr;  // Published to the watchdog by g_started.
std::array<TaskHandle_t, 2> g_producer_tasks{};
TaskHandle_t g_consumer_task = nullptr;

// Used only by the sequential tests, before the stress producers start.
struct Tracked {
  static inline uint32_t live = 0;
  static inline uint32_t constructed = 0;
  static inline uint32_t destroyed = 0;
  uint32_t value;

  explicit Tracked(uint32_t initial) noexcept : value(initial) {
    ++live;
    ++constructed;
  }
  ~Tracked() noexcept {
    --live;
    ++destroyed;
  }
  Tracked(const Tracked&) = delete;
  Tracked& operator=(const Tracked&) = delete;
};

bool Check(uart::Uart& uart, bool condition, std::string_view label) {
  if (!condition) {
    uart.Send("FAIL ");
    uart.Send(label);
    uart.Send("\r\n");
  }
  return condition;
}

bool PoolTest(uart::Uart& uart) {
  bool ok = true;
  Tracked::constructed = Tracked::destroyed = 0;
  {
    MemoryPool<Tracked, 3> pool;
    auto first = pool.create(11U);
    auto second = pool.create(22U);
    auto third = pool.create(33U);
    auto exhausted = pool.create(44U);
    ok &= Check(uart, first && second && third && !exhausted, "pool capacity");
    ok &= Check(uart, Tracked::live == 3, "pool constructs only successful allocations");
    if (first && second && third) {
      ok &= Check(
          uart,
          first.get() != second.get() && first.get() != third.get() && second.get() != third.get(),
          "pool distinct blocks");
      Tracked *released = second.get();
      second.reset();
      auto reused = pool.create(55U);
      ok &= Check(uart, reused && reused.get() == released && reused->value == 55, "pool reuse");
      ok &= Check(uart, first->value == 11 && third->value == 33, "pool retained values");
    }
  }
  ok &= Check(uart, Tracked::live == 0 && Tracked::constructed == 4 && Tracked::destroyed == 4,
              "pool lifetime");
  if (ok) uart.Send("PASS pool exhaustion/reuse/lifetime\r\n");
  return ok;
}

bool QueueTest(uart::Uart& uart) {
  bool ok = true;
  Tracked::constructed = Tracked::destroyed = 0;
  {
    MpscQueue<Tracked, 2> queue;
    ok &= Check(uart, queue.dequeue() == nullptr && Tracked::live == 0, "queue sentinel");
    ok &= Check(uart, queue.emplace(1U) && queue.emplace(2U) && !queue.emplace(99U),
                "queue capacity");
    auto *first = queue.dequeue();
    ok &= Check(uart, first && first->value == 1, "queue FIFO first");
    auto *second = queue.dequeue();
    ok &= Check(uart, second && second->value == 2 && Tracked::destroyed == 1,
                "queue FIFO and delayed destruction");
    ok &= Check(uart, queue.dequeue() == nullptr && Tracked::live == 1,
                "queue retains returned payload");
    // Leave these enqueued to exercise destruction of both pending and retained payloads.
    ok &= Check(uart, queue.emplace(3U) && queue.emplace(4U), "queue capacity reuse");
  }
  ok &= Check(uart, Tracked::live == 0 && Tracked::constructed == 4 && Tracked::destroyed == 4,
              "queue cleanup");
  if (ok) uart.Send("PASS queue FIFO/capacity/lifetime\r\n");
  return ok;
}

bool StorageTest(uart::Uart& uart) {
  bool ok = true;
  storage::ReferenceHolder<64> holder;
  holder.Store();
  ok &= Check(uart, std::tuple_size_v<decltype(holder.Retrieve())> == 0, "empty storage");
  holder.Store("x", uint8_t{7}, uint64_t{0x1122334455667788ULL});
  const auto values = holder.Retrieve<const char(&)[2], uint8_t, uint64_t>();
  ok &= Check(uart,
              std::string_view(std::get<0>(values)) == "x" && std::get<1>(values) == 7 &&
                  std::get<2>(values) == 0x1122334455667788ULL,
              "decayed array and mixed alignment");
  {
    console_log::impl::LogEntry entry(123, "ready");
    emio::static_buffer<64> buffer;
    ok &= Check(
        uart,
        !entry.Format(buffer).has_error() && buffer.view() == "ready" && entry.timestamp() == 123,
        "empty deferred format");
  }
  {
    console_log::impl::LogEntry entry(456, "{} {} {}", "x", uint8_t{7}, uint64_t{4294967298});
    emio::static_buffer<64> buffer;
    ok &= Check(uart, !entry.Format(buffer).has_error() && buffer.view() == "x 7 4294967298",
                "mixed deferred format");
  }
  if (ok) uart.Send("PASS storage/deferred-format\r\n");
  return ok;
}

bool Produce(uint32_t producer) {
  const uint32_t sequence = g_accepted[producer].load(std::memory_order_relaxed);
  if (sequence == kRecordsPerProducer) return false;
  if (g_queue.emplace(Record{producer, sequence, Checksum(producer, sequence)})) {
    g_accepted[producer].store(sequence + 1, std::memory_order_release);
    return true;
  }
  g_full[producer].fetch_add(1, std::memory_order_relaxed);
  return false;
}

void ProducerTask(void *argument) {
  const auto producer = *static_cast<const uint32_t *>(argument);
  while (!g_finished.load(std::memory_order_acquire)) {
    if (g_started.load(std::memory_order_acquire)) {
      for (uint32_t i = 0; i < 16 && Produce(producer); ++i) {}
    }
    // Yield even when full: a higher-priority producer must not starve the consumer.
    vTaskDelay(pdMS_TO_TICKS(1));
  }
  vTaskSuspend(nullptr);
}

void ConsumerTask(void *) {
  uart::Uart uart(uart::Id::kUart0);
  if (!uart.Configure()) {
    while (true) {}
  }
  g_uart = &uart;
  uart.Send("DIRECT_LINE_HW_TEST v1\r\n");
  const bool pool_ok = PoolTest(uart);
  const bool queue_ok = QueueTest(uart);
  const bool storage_ok = StorageTest(uart);
  if (!pool_ok || !queue_ok || !storage_ok) {
    g_finished.store(true, std::memory_order_release);
    uart.Send("RESULT FAIL sequential tests\r\n");
    vTaskSuspend(nullptr);
  }

  uart.Send("START MPSC tasks=2 ISR=1 records_each=10000 timer_us=100\r\n");
  std::array<uint32_t, kProducerCount> received{};
  uint32_t total = 0;
  bool valid = true;
  g_timer.SetPeriod(100);
  g_started.store(true, std::memory_order_release);
  g_timer.Start();
  const TickType_t start = xTaskGetTickCount();

  while (total < kProducerCount * kRecordsPerProducer && valid &&
         xTaskGetTickCount() - start < pdMS_TO_TICKS(kTimeoutMs - 1000)) {
    // A null result can be an unfinished publication. Always let task producers resume.
    for (uint32_t batch = 0; batch < 64; ++batch) {
      const Record *record = g_queue.dequeue();
      if (!record) break;
      if (record->producer >= kProducerCount || record->sequence != received[record->producer] ||
          record->checksum != Checksum(record->producer, record->sequence)) {
        valid = false;
        break;
      }
      ++received[record->producer];
      ++total;
    }
    vTaskDelay(pdMS_TO_TICKS(1));
  }

  g_timer.Stop();
  g_finished.store(true, std::memory_order_release);
  for (uint32_t producer = 0; producer < kProducerCount; ++producer) {
    valid &= received[producer] == kRecordsPerProducer;
    valid &= g_accepted[producer].load(std::memory_order_acquire) == kRecordsPerProducer;
    emio::static_buffer<128> buffer;
    (void)emio::format_to(buffer, "producer={} accepted={} received={} full_retries={}\r\n",
                          producer, g_accepted[producer].load(), received[producer],
                          g_full[producer].load());
    uart.Send(buffer.view());
  }
  {
    emio::static_buffer<160> buffer;
    (void)emio::format_to(buffer, "elapsed_ticks={} stack_free_words consumer={} p0={} p1={}\r\n",
                          xTaskGetTickCount() - start, uxTaskGetStackHighWaterMark(g_consumer_task),
                          uxTaskGetStackHighWaterMark(g_producer_tasks[0]),
                          uxTaskGetStackHighWaterMark(g_producer_tasks[1]));
    uart.Send(buffer.view());
  }
  uart.Send(valid ? "RESULT PASS 30000 ordered/checksummed records\r\n"
                  : "RESULT FAIL MPSC count/order/checksum/timeout\r\n");
  vTaskSuspend(nullptr);
}

void WatchdogTask(void *) {
  vTaskDelay(pdMS_TO_TICKS(kTimeoutMs));
  if (g_started.load(std::memory_order_acquire) && !g_finished.load(std::memory_order_acquire)) {
    // Higher priority than all test tasks: keep them suspended while reporting a stall.
    // A stuck ISR or disabled-interrupt fault still requires the external host timeout.
    vTaskSuspendAll();
    g_timer.Stop();
    g_uart->Send("RESULT FAIL watchdog timeout\r\n");
    while (true) {}
  }
  vTaskSuspend(nullptr);
}

}  // namespace

extern "C" void Timer0AHandler() {
  g_timer.ClearInterrupt();
  if (g_started.load(std::memory_order_acquire) && !g_finished.load(std::memory_order_acquire)) {
    (void)Produce(kIsrProducer);
  }
}

int main() {
  board::BoardInit();
  static std::array<StaticTask_t, 4> tcbs;
  static std::array<StackType_t, 1536> consumer_stack;
  static std::array<std::array<StackType_t, 512>, 2> producer_stacks;
  static std::array<StackType_t, 256> watchdog_stack;
  static std::array<uint32_t, 2> producer_ids{0, 1};
  g_consumer_task = xTaskCreateStatic(ConsumerTask, "test-consumer", consumer_stack.size(), nullptr,
                                      2, consumer_stack.data(), &tcbs[0]);
  for (size_t i = 0; i < producer_ids.size(); ++i) {
    g_producer_tasks[i] =
        xTaskCreateStatic(ProducerTask, "test-producer", producer_stacks[i].size(),
                          &producer_ids[i], 1, producer_stacks[i].data(), &tcbs[i + 1]);
  }
  xTaskCreateStatic(WatchdogTask, "test-watchdog", watchdog_stack.size(), nullptr, 3,
                    watchdog_stack.data(), &tcbs[3]);
  vTaskStartScheduler();
  return 0;
}
