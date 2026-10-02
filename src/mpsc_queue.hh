#pragma once

#include <atomic>
#include <memory>
#include <optional>
#include <type_traits>
#include <utility>

#include "src/memory_pool.hh"

// Multiple-producer, single-consumer queue backed by a fixed-capacity pool. Producers can be
// preempted between updating the tail and publishing the link to their node. Until they resume,
// dequeue() can return nullptr even if a later producer has completed an enqueue. Consumers must
// not spin waiting for a preempted lower-priority producer. The algorithm is not wait-free.
//
// Destruction requires all producers to have stopped and exclusive access by the consumer.
// Pool must provide allocate_raw()/release_raw() for N + 1 nodes; the default is the ARM exclusive-
// access memory pool. The pool parameter also allows lifecycle tests without target instructions.
template <typename T, size_t N, template <typename, size_t> class Pool = MemoryPool>
class MpscQueue {
 public:
  MpscQueue() noexcept;
  ~MpscQueue() noexcept;

  // Not copyable or moveable.
  MpscQueue(const MpscQueue&) = delete;
  MpscQueue& operator=(const MpscQueue&) = delete;
  MpscQueue(MpscQueue&&) = delete;
  MpscQueue& operator=(MpscQueue&&) = delete;

  // Construct a payload directly in the queue. Returns false if the pool is exhausted (including
  // nodes reserved by other producers). Payload construction/destruction must not throw, and
  // construction must be safe in the caller's context. Multiple producers may call concurrently.
  template <typename... Args>
  [[nodiscard]] bool emplace(Args&&...args) noexcept;

  template <typename U>
  [[nodiscard]] bool enqueue(U&& data) noexcept;

  // Return the next payload, or nullptr if no node is currently reachable. A returned pointer is
  // valid until the next successful dequeue() or queue destruction. Only one consumer may call
  // this method, and that consumer must finish using the payload before advancing the queue.
  T *dequeue() noexcept;

 private:
  struct Node;
  static_assert(std::atomic<Node *>::is_always_lock_free);
  static_assert(std::is_nothrow_destructible_v<T>);

  // The most recently dequeued node is retained as the sentinel until dequeue() advances again.
  Pool<Node, N + 1> node_pool_;
  std::atomic<Node *> tail_;
  Node *head_;
};

template <typename T, size_t N, template <typename, size_t> class Pool>
struct MpscQueue<T, N, Pool>::Node {
  Node() noexcept = default;

  template <typename... Args>
  explicit Node(std::in_place_t, Args&&...args) noexcept
      : data(std::in_place, std::forward<Args>(args)...) {}

  std::optional<T> data;
  std::atomic<Node *> next{nullptr};
};

template <typename T, size_t N, template <typename, size_t> class Pool>
inline MpscQueue<T, N, Pool>::MpscQueue() noexcept {
  // There is always at least one node in the pool. The initial sentinel has no payload.
  Node *const node = std::construct_at(node_pool_.allocate_raw());
  tail_.store(node, std::memory_order_relaxed);
  head_ = node;
}

template <typename T, size_t N, template <typename, size_t> class Pool>
inline MpscQueue<T, N, Pool>::~MpscQueue() noexcept {
  while (dequeue()) {}
  std::destroy_at(head_);
  node_pool_.release_raw(head_);
}

template <typename T, size_t N, template <typename, size_t> class Pool>
template <typename... Args>
inline bool MpscQueue<T, N, Pool>::emplace(Args&&...args) noexcept {
  static_assert(std::is_nothrow_constructible_v<T, Args...>);
  Node *const storage = node_pool_.allocate_raw();
  if (!storage) [[unlikely]] {
    return false;
  }
  Node *const node = std::construct_at(storage, std::in_place, std::forward<Args>(args)...);

  Node *const old_tail = tail_.exchange(node, std::memory_order_acq_rel);
  old_tail->next.store(node, std::memory_order_release);
  return true;
}

template <typename T, size_t N, template <typename, size_t> class Pool>
template <typename U>
inline bool MpscQueue<T, N, Pool>::enqueue(U&& data) noexcept {
  return emplace(std::forward<U>(data));
}

template <typename T, size_t N, template <typename, size_t> class Pool>
inline T *MpscQueue<T, N, Pool>::dequeue() noexcept {
  Node *const new_head = head_->next.load(std::memory_order_acquire);
  if (!new_head) {
    return nullptr;
  }
  std::destroy_at(head_);
  node_pool_.release_raw(head_);
  head_ = new_head;
  return &*head_->data;
}
