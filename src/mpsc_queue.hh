#pragma once

#include <atomic>
#include <optional>

#include "src/memory_pool.hh"

// Multiple Producer Single Consumer [MPSC] lock-free queue.  On destruction all remaining enqueued
// items are dequeued.
template <typename T, size_t N>
class MpscQueue {
 public:
  MpscQueue() noexcept;
  ~MpscQueue() noexcept;

  // Not copyable or moveable.
  MpscQueue(const MpscQueue&) = delete;
  MpscQueue& operator=(const MpscQueue&) = delete;
  MpscQueue(MpscQueue&&) = delete;
  MpscQueue& operator=(MpscQueue&&) = delete;

  // Enqueue data into the queue.  Data will be copied / moved depending on type of U.  Returns
  // false if queue is full and true if data was successfully enqueued.  This method is thread safe
  // and can be called from any context.
  template <typename U>
  bool enqueue(U&& data) noexcept;

  // Dequeue data from the queue.  If data is available it is returned and removed from the queue,
  // otherwise returns std::nullopt.  This method is not thread safe and must only be called from a
  // single context.
  std::optional<T> dequeue() noexcept;

 private:
  struct Node;
  static_assert(std::atomic<Node *>::is_always_lock_free);

  // Add one to requested max queue size as the most recently dequeued node remains allocated until
  // the next enqueue -> dequeue cycle.
  MemoryPool<Node, N + 1> node_pool_;
  std::atomic<Node *> tail_;
  Node *head_;
};

template <typename T, size_t N>
inline MpscQueue<T, N>::MpscQueue() noexcept {
  // Cannot be nullptr as there is a least one node in the pool.
  Node *const node = node_pool_.allocate_raw();
  node->next.store(nullptr, std::memory_order_relaxed);
  tail_.store(node, std::memory_order_relaxed);
  head_ = node;
}

template <typename T, size_t N>
inline MpscQueue<T, N>::~MpscQueue() noexcept {
  while (dequeue()) {}
}

template <typename T, size_t N>
template <typename U>
inline bool MpscQueue<T, N>::enqueue(U&& data) noexcept {
  Node *const node = node_pool_.allocate_raw();
  if (!node) [[unlikely]] {
    return false;
  }
  node->data = std::forward<U>(data);
  node->next.store(nullptr, std::memory_order_relaxed);

  Node *const old_tail = tail_.exchange(node, std::memory_order_acq_rel);

  old_tail->next.store(node, std::memory_order_release);

  return true;
}

template <typename T, size_t N>
inline std::optional<T> MpscQueue<T, N>::dequeue() noexcept {
  Node *const new_head = head_->next.load(std::memory_order_acquire);
  if (!new_head) {
    return std::nullopt;
  }
  node_pool_.release_raw(head_);
  head_ = new_head;
  return std::move(head_->data);
}

template <typename T, size_t N>
struct MpscQueue<T, N>::Node {
  T data;
  std::atomic<Node *> next;
};
