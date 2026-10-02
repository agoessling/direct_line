#pragma once

#include <atomic>
#include <cstdint>
#include <utility>

#include <emio/emio.hpp>

#include "src/log_entry.hh"
#include "src/mpsc_queue.hh"
#include "src/timer.hh"

namespace console_log {

class ConsoleLogger {
 public:
  explicit ConsoleLogger(timer::WrappingTimer& timer) noexcept : timer_{timer} {}

  // Arguments are stored by value, but format strings, character pointers and string_views are
  // borrowed: their characters must remain alive and unchanged until ProcessOne() consumes the
  // entry. String literals are safe. Log() can run in an ISR; formatting runs only in ProcessOne().
  template <typename... Ts>
  [[nodiscard]] bool Log(emio::format_string<Ts...> fmt, Ts&&...args) noexcept {
    if (queue_.emplace(timer_.Now(), fmt, std::forward<Ts>(args)...)) return true;
    dropped_entries_.fetch_add(1, std::memory_order_relaxed);
    return false;
  }

  // Total queue-full drops since construction, wrapping modulo 2^32.
  [[nodiscard]] uint32_t dropped_entries() const noexcept {
    return dropped_entries_.load(std::memory_order_relaxed);
  }

  // Single consumer only. An unavailable entry returns success without appending to the buffer.
  [[nodiscard]] emio::result<void> ProcessOne(emio::buffer& buffer) noexcept {
    const impl::LogEntry *const entry = queue_.dequeue();
    if (entry == nullptr) {
      return emio::success;
    }

    // Add timestamp.
    emio::result<void> result = emio::format_to(buffer, "[{:010d}] ", entry->timestamp());
    EMIO_TRYV(result);

    result = entry->Format(buffer);
    EMIO_TRYV(result);

    // Add newline.
    return emio::format_to(buffer, "\r\n");
  }

 private:
  static_assert(std::atomic<uint32_t>::is_always_lock_free);
  std::atomic<uint32_t> dropped_entries_{0};
  MpscQueue<impl::LogEntry, 16> queue_;
  timer::WrappingTimer& timer_;
};

}  // namespace console_log
