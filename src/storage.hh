#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <tuple>
#include <type_traits>

namespace storage {

// Utility for calculating various quantities associated with parameter pack's layout in memory.
template <typename... Ts>
struct Layout {
  static constexpr size_t kNumTypes = sizeof...(Ts);
  static constexpr std::array<size_t, kNumTypes> kSizes = {sizeof(Ts)...};
  static constexpr std::array<size_t, kNumTypes> kAlignments = {alignof(Ts)...};
  static constexpr std::array<size_t, kNumTypes> kOffsets = []() constexpr {
    std::array<size_t, kNumTypes> offsets;
    size_t offset = 0;
    for (size_t i = 0; i < kNumTypes; ++i) {
      offset = (offset + kAlignments[i] - 1) / kAlignments[i] * kAlignments[i];
      offsets[i] = offset;
      offset += kSizes[i];
    }
    return offsets;
  }();
  static constexpr size_t kTotalSize = kOffsets[kNumTypes - 1] + kSizes[kNumTypes - 1];
  static constexpr size_t kTotalAlignment =
      *std::max_element(kAlignments.begin(), kAlignments.end());
};

template <size_t N>
class ReferenceHolder {
 public:
  // Store the arguments in the reference holder.
  template <typename... Ts>
  void Store(Ts&&...args) noexcept {
    using L = Layout<Ts...>;

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
    return RetrieveImpl<Layout<Ts...>, Ts...>(std::index_sequence_for<Ts...>{});
  }

 private:
  template <typename L, typename... Ts, size_t... Is>
  void StoreImpl(std::index_sequence<Is...> /*indices*/, Ts&&...args) noexcept {
    ((new (buffer_.data() + L::kOffsets[Is]) std::decay_t<Ts>(std::forward<Ts>(args))), ...);
  }

  template <typename L, typename... Ts, size_t... Is>
  std::tuple<const std::decay_t<Ts>&...> RetrieveImpl(
      std::index_sequence<Is...> /*indices*/) const noexcept {
    return std::tie(
        *reinterpret_cast<const std::decay_t<Ts> *const>(buffer_.data() + L::kOffsets[Is])...);
  }

  alignas(std::max_align_t) std::array<std::byte, N> buffer_;
};

};  // namespace storage
