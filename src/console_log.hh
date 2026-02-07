#pragma once

#include <string_view>
#include <tuple>

#include <emio/emio.hpp>

#include "src/mpsc_queue.hh"
#include "src/storage.hh"
#include "src/timer.hh"

namespace console_log {

namespace impl {

class LogEntry {
 public:
  template <typename... Ts>
  LogEntry(uint32_t timestamp, emio::format_string<Ts...> fmt, Ts&&...args) noexcept
      : format_str_{fmt.get().assume_value()},
        format_func_{&LogEntry::FormatImpl<Ts...>},
        timestamp_{timestamp} {
    ref_holder_.template Store(std::forward<Ts>(args)...);
  }

  [[nodiscard]] emio::result<void> Format(emio::buffer& buffer) const noexcept {
    return format_func_(*this, buffer);
  }

  [[nodiscard]] uint32_t timestamp() const noexcept { return timestamp_; }

 private:
  using FormatFunc = emio::result<void> (*)(const LogEntry&, emio::buffer&);

  template <typename T, size_t... Is>
  [[nodiscard]] static emio::result<void> FormatImplWithArgs(
      emio::buffer& buffer, std::string_view format_str, const T& args,
      std::index_sequence<Is...> /*indices*/) noexcept {
    return emio::format_to(buffer, emio::runtime(format_str), std::get<Is>(args)...);
  }

  template <typename... Ts>
  [[nodiscard]] static emio::result<void> FormatImpl(const LogEntry& entry,
                                                     emio::buffer& buffer) noexcept {
    const auto& args = entry.ref_holder_.template Retrieve<Ts...>();
    return FormatImplWithArgs(buffer, entry.format_str_, args, std::index_sequence_for<Ts...>{});
  }

  storage::ReferenceHolder<64> ref_holder_;
  std::string_view format_str_;
  FormatFunc format_func_;
  uint32_t timestamp_;
};

};  // namespace impl

class ConsoleLogger {
 public:
  explicit ConsoleLogger(timer::WrappingTimer& timer) noexcept : timer_{timer} {}

  template <typename... Ts>
  bool Log(emio::format_string<Ts...> fmt, Ts&&...args) {
    return queue_.enqueue(impl::LogEntry{timer_.Now(), fmt, std::forward<Ts>(args)...});
  }

  emio::result<void> ProcessOne(emio::buffer& buffer) {
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
  MpscQueue<impl::LogEntry, 16> queue_;
  timer::WrappingTimer& timer_;
};

};  // namespace console_log
