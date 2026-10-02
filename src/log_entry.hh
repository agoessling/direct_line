#pragma once

#include <cstdint>
#include <string_view>
#include <tuple>
#include <utility>

#include <emio/emio.hpp>

#include "src/storage.hh"

namespace console_log {

namespace impl {

// Stored in-place in the queue: arguments are copied/moved once at enqueue time, then formatted
// by the consumer. The format string and any argument pointees remain borrowed.
class LogEntry {
 public:
  template <typename... Ts>
  LogEntry(uint32_t timestamp, emio::format_string<Ts...> fmt, Ts&&...args) noexcept
      : format_str_{fmt.get()}, format_func_{&LogEntry::FormatImpl<Ts...>}, timestamp_{timestamp} {
    ref_holder_.template Store(std::forward<Ts>(args)...);
  }

  [[nodiscard]] emio::result<void> Format(emio::buffer& buffer) const noexcept {
    if (format_str_.has_error()) return format_str_.assume_error();
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
    return FormatImplWithArgs(buffer, entry.format_str_.assume_value(), args,
                              std::index_sequence_for<Ts...>{});
  }

  storage::ReferenceHolder<64> ref_holder_;
  emio::result<std::string_view> format_str_;
  FormatFunc format_func_;
  uint32_t timestamp_;
};

}  // namespace impl

}  // namespace console_log
