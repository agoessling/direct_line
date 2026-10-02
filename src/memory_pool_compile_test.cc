// Cross-compile coverage for the real ARM allocator. This is not an on-target runtime test.
#include "src/memory_pool.hh"
#include "src/mpsc_queue.hh"

namespace {

struct Payload {
  explicit Payload(int value) noexcept : value(value) {}
  ~Payload() noexcept { value = 0; }
  Payload(const Payload&) = delete;
  Payload(Payload&&) = delete;
  Payload& operator=(const Payload&) = delete;
  Payload& operator=(Payload&&) = delete;

  int value;
};

}  // namespace

// An externally visible function keeps the allocator and queue operations in the object file.
// Instantiating both counter configurations checks their ARM assembly and template paths.
int CompileMemoryPoolAndQueue() {
  MemoryPool<Payload, 2, true> pool;
  auto first = pool.create(1);
  auto second = pool.create(2);
  auto exhausted = pool.create(3);
  int result = first->value + second->value;
  first.reset();
  first = pool.create(4);
  result += first->value;
  result += pool.get_debug_counters().successful_allocations.load();
  result += exhausted != nullptr;

  MemoryPool<int, 0> empty;
  result += empty.allocate_raw() != nullptr;

  MpscQueue<Payload, 2> queue;
  if (queue.emplace(result)) {
    result = queue.dequeue()->value;
  }
  return result;
}
