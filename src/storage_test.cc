#include "src/storage.hh"

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

namespace {

// A trivial destructor does not imply that copying an object's bytes is valid.
struct AddressAware {
  explicit AddressAware(int value) noexcept : value{value} {}
  AddressAware(const AddressAware& other) noexcept : value{other.value}, self{this} {}
  int value;
  const AddressAware *self = this;
};

struct alignas(std::max_align_t) AlignedValue {
  int value;
};

static_assert(storage::Layout<>::kTotalSize == 0);
static_assert(storage::Layout<>::kTotalAlignment == 1);
static_assert(!std::is_copy_constructible_v<storage::ReferenceHolder<64>>);
static_assert(!std::is_move_constructible_v<storage::ReferenceHolder<64>>);
static_assert(std::is_trivially_destructible_v<AddressAware>);

}  // namespace

int main() {
  storage::ReferenceHolder<0> empty;
  empty.Store();
  CHECK(empty.Retrieve() == std::tuple<>{});

  // Both a leading byte and trailing byte expose the old array-size/pointer-size layout bug.
  const char text[] = "a";
  storage::ReferenceHolder<64> mixed;
  mixed.Store(uint8_t{7}, text, uint8_t{9});
  const auto mixed_args = mixed.Retrieve<uint8_t, decltype(text)&, uint8_t>();
  CHECK(std::get<0>(mixed_args) == 7);
  CHECK(std::get<1>(mixed_args) == text);
  CHECK(std::string_view{std::get<1>(mixed_args)} == "a");
  CHECK(std::get<2>(mixed_args) == 9);

  int source = 123;
  storage::ReferenceHolder<64> values;
  values.Store(source, uint8_t{4}, AlignedValue{17});
  source = 456;
  const auto value_args = values.Retrieve<int&, uint8_t, AlignedValue>();
  CHECK(std::get<0>(value_args) == 123);
  CHECK(std::get<1>(value_args) == 4);
  CHECK(std::get<2>(value_args).value == 17);
  CHECK(reinterpret_cast<uintptr_t>(&std::get<2>(value_args)) % alignof(AlignedValue) == 0);

  const AddressAware original{42};
  storage::ReferenceHolder<64> objects;
  objects.Store(original);
  const auto& copy = std::get<0>(objects.Retrieve<const AddressAware&>());
  CHECK(copy.value == 42);
  CHECK(copy.self == &copy);
  CHECK(&copy != &original);

  // Reusing storage ends the previous trivially destructible object's lifetime.
  objects.Store(uint32_t{99});
  CHECK(std::get<0>(objects.Retrieve<uint32_t>()) == 99);
  return 0;
}
