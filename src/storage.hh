#pragma once

#include <array>
#include <cstddef>
#include <new>
#include <tuple>
#include <type_traits>
#include <utility>

namespace storage {

// Utility for calculating various quantities associated with parameter pack's layout in memory.
template <typename... Ts>
struct Layout {
  static constexpr size_t kNumTypes = sizeof...(Ts);
  static constexpr std::array<size_t, kNumTypes> kSizes = {sizeof(Ts)...};
  static constexpr std::array<size_t, kNumTypes> kAlignments = {alignof(Ts)...};
  static constexpr std::array<size_t, kNumTypes> kOffsets = []() constexpr {
    std::array<size_t, kNumTypes> offsets{};
    size_t offset = 0;
    for (size_t i = 0; i < kNumTypes; ++i) {
      offset = (offset + kAlignments[i] - 1) / kAlignments[i] * kAlignments[i];
      offsets[i] = offset;
      offset += kSizes[i];
    }
    return offsets;
  }();
  static constexpr size_t kTotalSize = []() constexpr {
    if constexpr (kNumTypes == 0) {
      return size_t{0};
    } else {
      return kOffsets[kNumTypes - 1] + kSizes[kNumTypes - 1];
    }
  }();
  static constexpr size_t kTotalAlignment = []() constexpr {
    size_t alignment = 1;
    for (size_t value : kAlignments) {
      if (value > alignment) alignment = value;
    }
    return alignment;
  }();
};

template <size_t N>
class ReferenceHolder {
 public:
  ReferenceHolder() noexcept = default;

  // Copying bytes does not copy-construct stored objects. Keep their addresses stable instead.
  ReferenceHolder(const ReferenceHolder&) = delete;
  ReferenceHolder& operator=(const ReferenceHolder&) = delete;
  ReferenceHolder(ReferenceHolder&&) = delete;
  ReferenceHolder& operator=(ReferenceHolder&&) = delete;

  // Store decayed argument values. Pointers and views borrow their referents; arrays decay to
  // pointers. Referenced data must remain valid for any later use of the retrieved values.
  template <typename... Ts>
  void Store(Ts&&...args) noexcept {
    using L = Layout<std::decay_t<Ts>...>;

    static_assert(L::kTotalSize <= N, "Buffer too small for provided types.");
    static_assert(L::kTotalAlignment <= alignof(std::max_align_t),
                  "Buffer alignment is insufficient.");
    static_assert((std::is_nothrow_constructible_v<std::decay_t<Ts>, Ts&&> && ...),
                  "All provided types must be nothrow constructible.");
    static_assert((std::is_trivially_destructible_v<std::decay_t<Ts>> && ...),
                  "All provided types must be trivially destructible.");

    StoreImpl<L>(std::index_sequence_for<Ts...>{}, std::forward<Ts>(args)...);
  }

  // Retrieve the previously stored arguments.  Must be called with the same template parameters as
  // the previous Store().
  template <typename... Ts>
  std::tuple<const std::decay_t<Ts>&...> Retrieve() const noexcept {
    return RetrieveImpl<Layout<std::decay_t<Ts>...>, Ts...>(std::index_sequence_for<Ts...>{});
  }

 private:
  template <typename L, typename... Ts, size_t... Is>
  void StoreImpl(std::index_sequence<Is...> /*indices*/, Ts&&...args) noexcept {
    ((new (buffer_.data() + L::kOffsets[Is]) std::decay_t<Ts>(std::forward<Ts>(args))), ...);
  }

  template <typename L, typename... Ts, size_t... Is>
  std::tuple<const std::decay_t<Ts>&...> RetrieveImpl(
      std::index_sequence<Is...> /*indices*/) const noexcept {
    return std::tie(*std::launder(
        reinterpret_cast<const std::decay_t<Ts> *>(buffer_.data() + L::kOffsets[Is]))...);
  }

  alignas(std::max_align_t) std::array<std::byte, N> buffer_;
};

}  // namespace storage
