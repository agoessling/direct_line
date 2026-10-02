#include "src/log_entry.hh"

#include <cstdint>
#include <cstdio>
#include <string_view>
#include <type_traits>

#define CHECK(condition)                                                           \
  do {                                                                             \
    if (!(condition)) {                                                            \
      std::fprintf(stderr, "Check failed at line %d: %s\n", __LINE__, #condition); \
      return 1;                                                                    \
    }                                                                              \
  } while (false)

using console_log::impl::LogEntry;

static_assert(!std::is_copy_constructible_v<LogEntry>);
static_assert(!std::is_move_constructible_v<LogEntry>);

int main() {
  LogEntry empty{12, "started"};
  emio::static_buffer<128> buffer;
  CHECK(empty.timestamp() == 12);
  CHECK(empty.Format(buffer).has_value());
  CHECK(buffer.view() == "started");

  int counter = 42;
  const char text[] = "a";
  LogEntry mixed{34, "{} {} {} {}", uint8_t{7}, text, uint8_t{9}, counter};
  counter = 99;
  buffer.reset();
  CHECK(mixed.Format(buffer).has_value());
  CHECK(buffer.view() == "7 a 9 42");

  // Borrowed views are supported when the characters outlive formatting.
  LogEntry view{56, "value={:04x} {}", uint32_t{31}, std::string_view{"ok"}};
  buffer.reset();
  CHECK(view.Format(buffer).has_value());
  CHECK(buffer.view() == "value=001f ok");

  emio::static_buffer<2> too_small;
  CHECK(empty.Format(too_small).has_error());

  LogEntry invalid{78, emio::runtime("{")};
  buffer.reset();
  CHECK(invalid.Format(buffer).has_error());
  CHECK(buffer.view().empty());
  return 0;
}
