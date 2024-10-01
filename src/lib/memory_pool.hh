#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <ranges>
#include <utility>

template <typename T, size_t N, bool Debug = false>
class MemoryPool {
 private:
  class BlockDeleter;

 public:
  using UniquePtr = std::unique_ptr<T, BlockDeleter>;

  MemoryPool() noexcept;

  // Constructs in place a T in newly allocated memory.  Args are forwarded to the constructor of T.
  // If no memory is available returns an empty (nullptr) UniquePtr.
  template <typename... Args>
  UniquePtr create(Args&&...args) noexcept;

  // Constructs in place a T in newly allocated memory. The initializer list is forwarded to the
  // constructor of T. If no memory is available returns an empty (nullptr) UniquePtr.
  template <typename U>
  UniquePtr create(std::initializer_list<U> ilist) noexcept;

  // Allocates memory from the pool and returns a pointer to a default initialized instance of T.
  // If no memory is available returns an empty (nullptr) UniquePtr.
  UniquePtr allocate() noexcept;

 private:
  class Block;
  struct DebugCounters;

  T *allocate_raw() noexcept;
  void release(T *ptr) noexcept;

  std::array<Block, N> blocks_;  // Storage for memory pool.
  Block *head_;  // Pointer to the next block to be allocated.
  DebugCounters counters_;
};

// A block of raw memory which can either store a T or a pointer to the next block.
template <typename T, size_t N, bool Debug>
class MemoryPool<T, N, Debug>::Block {
 public:
  static constexpr size_t kSize = std::max(sizeof(T), sizeof(Block *));

  T *data() {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast)
    return reinterpret_cast<T *>(&buffer_);
  }

  Block **next() {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast)
    return reinterpret_cast<Block **>(&buffer_);
  }

 private:
  alignas(T) alignas(Block *) std::array<std::byte, kSize> buffer_;
};

// Deleter used with unique_ptr to release block.
template <typename T, size_t N, bool Debug>
class MemoryPool<T, N, Debug>::BlockDeleter {
 public:
  explicit BlockDeleter(MemoryPool<T, N, Debug> *pool) noexcept : pool_{pool} {}

  void operator()(T *ptr) noexcept {
    ptr->~T();
    pool_->release(ptr);
  }

 private:
  MemoryPool<T, N, Debug> *pool_;
};

template <typename T, size_t N, bool Debug>
struct MemoryPool<T, N, Debug>::DebugCounters {
  std::atomic<uint32_t> successful_allocations;
  std::atomic<uint32_t> failed_allocations;
  std::atomic<uint32_t> successful_releases;
  std::atomic<uint32_t> failed_releases;
};
static_assert(std::atomic<uint32_t>::is_always_lock_free);

template <typename T, size_t N, bool Debug>
inline MemoryPool<T, N, Debug>::MemoryPool() noexcept {
  // Initialize linked list.
  Block *next = nullptr;
  for (Block& block : std::views::reverse(blocks_)) {
    *block.next() = next;
    next = &block;
  }
  head_ = next;
}

template <typename T, size_t N, bool Debug>
template <typename... Args>
inline MemoryPool<T, N, Debug>::UniquePtr MemoryPool<T, N, Debug>::create(Args&&...args) noexcept {
  T *const ptr = allocate_raw();
  if (ptr) [[likely]] {
    if constexpr (std::is_aggregate_v<T>) {
      return UniquePtr(new (ptr) T{std::forward<Args>(args)...}, BlockDeleter(this));
    } else {
      return UniquePtr(new (ptr) T(std::forward<Args>(args)...), BlockDeleter(this));
    }
  }
  return UniquePtr(nullptr, BlockDeleter(this));
}

template <typename T, size_t N, bool Debug>
template <typename U>
inline MemoryPool<T, N, Debug>::UniquePtr MemoryPool<T, N, Debug>::create(
    std::initializer_list<U> ilist) noexcept {
  T *const ptr = allocate_raw();
  if (ptr) [[likely]] {
    return UniquePtr(new (ptr) T(ilist), BlockDeleter(this));
  }
  return UniquePtr(nullptr, BlockDeleter(this));
}

template <typename T, size_t N, bool Debug>
inline MemoryPool<T, N, Debug>::UniquePtr MemoryPool<T, N, Debug>::allocate() noexcept {
  T *const ptr = allocate_raw();
  if (ptr) [[likely]] {
    return UniquePtr(new (ptr) T, BlockDeleter(this));
  }
  return UniquePtr(nullptr, BlockDeleter(this));
}

template <typename T, size_t N, bool Debug>
inline T *MemoryPool<T, N, Debug>::allocate_raw() noexcept {
  while (true) {
    // Load acquire exclusive head_ from memory to old_head a register.
    // This does two things: First synchronizes any writes prior to this load (acquire).  Second,
    // initiates the exclusive access state machine. "memory" implements a read/write compiler
    // memory barrier.
    Block *old_head = nullptr;
    asm("ldaex %0 %1" : "=r"(old_head) : "m"(head_) : "memory");

    if (old_head == nullptr) [[unlikely]] {
      return nullptr;
    }

    Block *const new_head = *old_head->next();

    // Store release exclusive new_head (a register) to memory of head_.  This will only succeed
    // if no exclusive stores have occured since the load exclusive.  This protects against
    // preemption in between the load and store, as well as instruction reordering.  Because the
    // store will fail for any modification of head_ not just when the value differs, this also
    // solves the ABA problem. "memory" implements a read/write compiler memory barrier.
    uint32_t failed = 1;
    asm("stlex %0 %1 %2" : "=r"(failed) : "r"(new_head), "m"(head_) : "memory");

    if (failed == 0) [[likely]] {
      if constexpr (Debug) {
        counters_.successful_allocations++;
      }
      return old_head->data();
    }

    if constexpr (Debug) {
      counters_.failed_allocations++;
    }
  }
}

template <typename T, size_t N, bool Debug>
inline void MemoryPool<T, N, Debug>::release(T *ptr) noexcept {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast)
  const auto block = reinterpret_cast<Block *>(ptr);

  while (true) {
    // Load acquire exclusive head_ from memory to old_head a register.
    // This does two things: First synchronizes any writes prior to this load (acquire).  Second
    // initiates the exclusive access state machine. "memory" implements a read/write compiler
    // memory barrier.
    Block *old_head = nullptr;
    asm("ldaex %0 %1" : "=r"(old_head) : "m"(head_) : "memory");

    *block->next() = old_head;

    // Store release exclusive block (a register) to memory of head_.  This will only succeed
    // if no exclusive stores have occured since the load exclusive.  This protects against
    // preemption in between the load and store, as well as instruction reordering.  Because the
    // store will fail for any modification of head_ not just when the value differs, this also
    // solves the ABA problem. "memory" implements a read/write compiler memory barrier.
    uint32_t failed = 1;
    asm("stlex %0 %1 %2" : "=r"(failed) : "r"(block), "m"(head_) : "memory");

    if (failed == 0) [[likely]] {
      if constexpr (Debug) {
        counters_.successful_releases++;
      }
      return;
    }

    if constexpr (Debug) {
      counters_.failed_releases++;
    }
  }
}
