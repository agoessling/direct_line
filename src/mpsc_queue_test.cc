#include "src/mpsc_queue.hh"

#include <array>
#include <cstdio>
#include <cstdlib>
#include <memory>

namespace {

void Check(bool condition) {
  if (!condition) {
    std::fputs("Queue lifecycle/capacity check failed\n", stderr);
    std::abort();
  }
}

// Sequential test allocator: validates every release and that queue destruction returns all
// nodes, including the sentinel. It deliberately does not model the ARM pool or concurrency.
template <typename T, size_t N>
class TestPool {
 public:
  ~TestPool() {
    for (const auto& slot : slots_) {
      Check(!slot.used);
    }
  }

  T *allocate_raw() noexcept {
    for (auto& slot : slots_) {
      if (!slot.used) {
        slot.used = true;
        return reinterpret_cast<T *>(slot.storage.data());
      }
    }
    return nullptr;
  }

  void release_raw(T *ptr) noexcept {
    for (auto& slot : slots_) {
      if (reinterpret_cast<T *>(slot.storage.data()) == ptr) {
        Check(slot.used);
        slot.used = false;
        return;
      }
    }
    Check(false);
  }

 private:
  struct Slot {
    alignas(T) std::array<std::byte, sizeof(T)> storage;
    bool used = false;
  };
  std::array<Slot, N> slots_;
};

struct Lifetime {
  int constructed = 0;
  int destroyed = 0;
};

struct Payload {
  Payload(Lifetime& lifetime, int value) noexcept : lifetime(lifetime), value(value) {
    ++lifetime.constructed;
  }
  ~Payload() noexcept { ++lifetime.destroyed; }
  Payload(const Payload&) = delete;
  Payload(Payload&&) = delete;
  Payload& operator=(const Payload&) = delete;
  Payload& operator=(Payload&&) = delete;

  Lifetime& lifetime;
  int value;
};

void NonmovablePayloadLifetime() {
  Lifetime lifetime;
  {
    MpscQueue<Payload, 2, TestPool> queue;
    Check(lifetime.constructed == 0);  // Empty sentinel does not construct T.
    Check(queue.dequeue() == nullptr);
    Check(queue.emplace(lifetime, 1));
    Check(queue.emplace(lifetime, 2));
    Check(!queue.emplace(lifetime, 3));
    Check(lifetime.constructed == 2);  // Failed enqueue must not construct T.
    Payload *first = queue.dequeue();
    Check(first && first->value == 1);
    Check(lifetime.destroyed == 0);  // Returned value stays alive.
    Check(queue.emplace(lifetime, 3));
    Payload *second = queue.dequeue();
    Check(second && second->value == 2);
    Check(lifetime.destroyed == 1);
    // Leave both the returned payload and an unconsumed payload for the destructor.
  }
  Check(lifetime.constructed == 3);
  Check(lifetime.destroyed == 3);
}

void EmptyAndZeroCapacity() {
  Lifetime lifetime;
  {
    MpscQueue<Payload, 0, TestPool> queue;
    Check(!queue.emplace(lifetime, 1));
    Check(queue.dequeue() == nullptr);
  }
  Check(lifetime.constructed == 0);
  Check(lifetime.destroyed == 0);

  {
    MpscQueue<Payload, 1, TestPool> queue;
    Check(queue.emplace(lifetime, 7));
    Payload *value = queue.dequeue();
    Check(value && value->value == 7);
    Check(queue.dequeue() == nullptr);
    Check(lifetime.destroyed == 0);
    Check(value->value == 7);  // Unsuccessful dequeue retains the previous payload.
  }
  Check(lifetime.destroyed == 1);
}

void OwningPayloads() {
  Lifetime lifetime;
  {
    MpscQueue<std::unique_ptr<Payload>, 2, TestPool> queue;
    auto first = std::make_unique<Payload>(lifetime, 4);
    Check(queue.enqueue(std::move(first)));
    Check(!first);
    Check(queue.enqueue(std::make_unique<Payload>(lifetime, 5)));
    auto *entry = queue.dequeue();
    Check(entry && (*entry)->value == 4);
    auto extracted = std::move(*entry);
    Check(queue.dequeue() != nullptr);
    Check(lifetime.destroyed == 0);  // Moving ownership out survives node destruction.
    extracted.reset();
    Check(lifetime.destroyed == 1);
  }
  Check(lifetime.constructed == 2);
  Check(lifetime.destroyed == 2);
}

void ReuseAndFifo() {
  MpscQueue<int, 3, TestPool> queue;
  for (int i = 0; i < 100; ++i) {
    Check(queue.enqueue(i));
    Check(queue.emplace(i + 1));
    Check(queue.emplace(i + 2));
    Check(!queue.emplace(i + 3));
    for (int j = 0; j < 3; ++j) {
      int *value = queue.dequeue();
      Check(value && *value == i + j);
    }
    Check(queue.dequeue() == nullptr);
  }
}

}  // namespace

int main() {
  NonmovablePayloadLifetime();
  EmptyAndZeroCapacity();
  OwningPayloads();
  ReuseAndFifo();
}
