# Safe, fast primitives for a small MCU

## The machine is part of the design

A small wireless controller needs predictable work more than it needs a universally reusable concurrency library. An interrupt should record an event and return. A task should consume that event without guessing whether its storage still belongs to it. Allocating a packet descriptor should have a known memory cost, and overload should produce a deliberate failure rather than corruption.

Those goals justify strong restrictions. A primitive that supports one Cortex-M33 core, a particular compiler ABI, and a specified set of interrupt priorities can be a better design than a portable primitive that supports arbitrary processors and thread schedulers. The restrictions become part of the implementation: state them, enforce the ones that can be enforced, and test the remaining assumptions on the target.

This chapter reviews the queue, pool, deferred argument storage, and critical-section guard in Direct Line. **Previous** means the implementation in commit `171168ef97ae0f9073f0a2c01f24e50f173833f7`. **Current** means the subsequent working-tree cleanup. **Proposed** means a design direction that has not been implemented or validated yet. In particular, successful compilation and host tests do not amount to a proof of interrupt safety.

The relevant implementations are [MpscQueue](../src/mpsc_queue.hh), [MemoryPool](../src/memory_pool.hh), [ReferenceHolder](../src/storage.hh), [LogEntry](../src/log_entry.hh), [ConsoleLogger](../src/console_log.hh), and [CriticalSectionGuard](../src/interrupt.hh).

The current target is the CC1354P10's Cortex-M33 application processor, built with Arm GNU 13.2.Rel1, C++23, and exceptions disabled. The argument below assumes a single participating core and ordinary, suitably aligned SRAM. It excludes DMA and the radio core from modifying allocator metadata. It also excludes concurrent destruction, invalid releases, and the use of a returned pointer after its documented lifetime.

“Low-power MCU” alone is not a sufficient architecture contract. A different core may lack the exclusive instructions used here, and a different memory region may have different exclusive-access behavior. A supported-target list should eventually identify the processor, compiler, relevant flags, memory placement, security state, and interrupt/context-switch model. Unsupported combinations should fail compilation rather than quietly selecting an unreviewed implementation.

## 1. Four separate questions about correctness

There are four questions to answer for each primitive:

1. **Object validity:** does a live object of the right type occupy the storage being accessed?
2. **Ownership and ordering:** who can modify that object, and how does another context learn that initialization is complete?
3. **Progress:** can an interrupted context prevent another context from obtaining useful work?
4. **Execution cost:** how much time and memory does the operation consume under the actual workload?

Atomic pointers address only part of this list. A perfectly atomic publication can publish an object that was never constructed. A correct free-list update can follow an invalid speculative read. A queue method can return quickly while making no useful progress because a producer was interrupted.

It helps to distinguish three terms. A lock-free operation offers system-wide progress rather than requiring a particular paused participant to resume. A wait-free operation has a bound on its own algorithmic steps. A bounded interrupt handler additionally needs bounded payload work and acceptable interference from higher-priority interrupts. None of these descriptions follows simply from using `std::atomic`.

For this project, useful performance measurements include uncontended cycles, maximum observed cycles under a defined interrupt workload, retry counts, masked-interrupt duration, queue residence time, RAM, flash, and energy per delivered event. Percentiles help describe normal behavior; a worst-case requirement needs an interference model as well. This chapter reports object sizes, not measured execution-time improvements.

## 2. Storage does not automatically provide a generic object

### The assignment that looked like construction

The previous queue allocated a raw node and then assigned its payload:

```cpp
Node *node = node_pool_.allocate_raw();
node->data = std::forward<U>(data);
```

That cannot implement a general `T` queue. Consider a payload that owns a radio-buffer slot. Its move assignment releases its previous slot before accepting a new one. Its destructor returns its slot to the packet pool. Assigning into raw storage invokes assignment without establishing the destination object's required state. The attempted release can use garbage or bytes left by the free list.

Even when assignment happens to work for the current scalar-like payload, that does not validate the generic interface. C++ has implicit object-creation rules for certain types and operations, so “every write into raw storage is invalid” would be too broad a claim. The problem is that those rules do not construct arbitrary resource-owning class objects or make their assignment operators safe. Explicit construction gives the queue a much clearer contract. See the language's [object-creation rules](https://eel.is/c++draft/intro.object).

The current queue instead constructs a node in place:

```cpp
Node *node = std::construct_at(storage, std::in_place,
                               std::forward<Args>(args)...);
```

Its node contains `std::optional<T>`. An empty optional represents the initial sentinel; an engaged optional contains a constructed payload. `emplace()` permits payloads that cannot be copied or moved, which is particularly useful for deferred argument storage containing address-sensitive objects.

This does not imply heap allocation. Placement construction uses storage that the pool already owns. For simple payloads, constructing the object can compile to the same necessary stores that a hand-written implementation would use. Whether a particular wrapper disappears is an assembly question, not a reason to omit lifetime management.

### Destruction has observable embedded consequences

The previous consumer returned a node to the raw pool without destroying its payload. The queue destructor repeatedly called `dequeue()`, which still did not destroy payloads, and left the final sentinel allocation outstanding.

A missing destructor can leak a packet slot, a DMA descriptor lease, or a peripheral ownership token. No heap is needed for this failure. After enough iterations, the application can exhaust resources despite having consumed every message.

The current consumer destroys the previous head before returning its storage. Queue destruction drains reachable entries, then destroys and releases the final head. This requires producers to have stopped: destruction is not a concurrent cancellation mechanism.

The returned payload has deliberately delayed destruction. If `dequeue()` returns `p`, the object remains alive until the next **successful** dequeue or queue destruction. A failed dequeue leaves it intact. This permits processing without another payload copy, at the cost of retaining one node and one payload after the queue has logically drained.

```cpp
auto *entry = queue.dequeue();
if (entry) {
  Process(*entry);       // Valid while this consumer retains the head.
}
auto *next = queue.dequeue();
// If this call succeeded, entry must no longer be used.
```

The queue now requires nothrow construction and destruction. That is necessary for its unconditional `noexcept` interface, but it does not prove that a constructor is short, allocation-free, or legal in an ISR. An accepted-payload policy remains useful even with those type traits.

## 3. The MPSC queue: publication in two steps

### Why the common path is attractive

The queue keeps a consumer-owned `head_` and an atomic producer `tail_`. Each producer obtains a private node, initializes it, exchanges the tail, and connects the previous tail to the new node:

```cpp
Node *previous = tail_.exchange(node, std::memory_order_acq_rel);
previous->next.store(node, std::memory_order_release);
```

The consumer reads `head_->next` with acquire ordering. If a node is available, it advances and recycles the old head. There is no search through the queue and no payload copy on dequeue.

There are two publication relationships to preserve. A later producer obtains the previous producer's node through the tail exchange and writes its `next` member. The consumer obtains a node through the published link and reads its payload. Initialization must precede these accesses. The acquire/release operations express those relationships; replacing the exchange with a relaxed operation simply because the processor has one core would discard part of the compiler-level argument. The relevant language rule is [release/acquire synchronization](https://eel.is/c++draft/atomics.order).

Also, an atomic exchange on an MCU need not be a single hardware exchange instruction. It can itself use an exclusive-access retry loop. The queue's enqueue cost includes allocation, construction, the atomic exchange, and link publication. Counting only the two lines above understates the full operation.

### A producer can leave a hole in the chain

Consider two producers, A and B, and a consumer C. `S` is the initial sentinel.

| Step | Context | State or action |
|---|---|---|
| 1 | Initial | `head = tail = S`; `S.next = null` |
| 2 | A | Constructs node `a`; exchanges `tail` to `a`, receiving `S` |
| 3 | A | Is preempted before storing `S.next = a` |
| 4 | B | Constructs `b`; exchanges `tail` to `b`, receiving `a` |
| 5 | B | Stores `a.next = b` and returns success |
| 6 | C | Reads `S.next`, which is still null |
| 7 | A, later | Stores `S.next = a`; both entries become reachable |

The consumer cannot reach `b` at step 6 even though B finished before the dequeue began. Increasing memory-order strength cannot publish the missing link on A's behalf.

This is why the old “null means empty” contract was too strong. Under a conventional linearizable FIFO contract, B's completed enqueue cannot simply disappear from a later empty observation. The current contract says that no node is **currently reachable**. The algorithm family's producer-dependent consumer progress is also described by [Vyukov's MPSC queue discussion](https://sites.google.com/site/1024cores/home/lock-free-algorithms/queues/intrusive-mpsc-node-based-queue).

Calling the current structure a fully lock-free FIFO without qualification would therefore be misleading. Its operations can return, but delivery of reachable work can depend on a particular producer resuming. With a finite pool, continued producers can eventually exhaust capacity behind that hole.

The scheduling consequence matters more than the terminology. A high-priority task that loops until dequeue succeeds can starve the lower-priority producer whose unfinished publication it needs. A timeout does not repair the missing link either; the producer must eventually run. Producer cancellation in this interval is incompatible with this algorithm.

### A useful restriction can eliminate this observation

Suppose all runtime producers are ISRs, the consumer runs only in task context, and there is only one core. The task cannot execute in the middle of an active producer ISR. Nested producer interrupts can create a temporary hole, but the interrupted ISR resumes and completes before task execution resumes, assuming handlers return normally.

Under that topology, the task consumer cannot observe the particular publication gap above. This is a valuable restriction, not a general proof for every use of the queue. It excludes task producers after concurrent operation starts, ISR consumers, producer cancellation, and a second core. Startup production before interrupts begin can be a separate, nonconcurrent phase. The current example—startup logging followed by timer-ISR production and task consumption—fits that intended shape.

An ISR-only interface could make this contract visible. Debug builds could check the current execution context, while initialization uses a separate entry point. Such a check establishes task versus ISR context, not which of several interrupts owns an endpoint. Target tests must exercise nesting and verify the configured priority relationships. If future task logging is required, the restriction must be reconsidered explicitly.

## 4. The memory pool: making use of the exclusive monitor

### Why overlaying storage is economical

The pool contains fixed-size blocks. A free block stores the address of the next free block in the same bytes that will later hold `T`. A leased block uses those bytes for its payload. A head pointer identifies the next available block.

This saves a separate link field per block. Ignoring aggregate padding, each block needs the larger of the payload and pointer sizes, rounded for their alignment. The block transitions between these states:

```text
free-list link -> reserved raw storage -> live payload
              -> destroyed payload -> free-list link
```

The owning `UniquePtr` path constructs a payload, destroys it through its deleter, and returns the block. Raw allocation exposes the same transitions to the caller. Its preconditions include a correct originating pool, exactly one release, no outstanding users, and destruction of any nontrivial payload before release.

Those preconditions are not checked by the current raw API. A double release can form a free-list cycle; a foreign pointer can insert unrelated memory. Trusted internal use can reasonably omit expensive checks in production, but checked builds should make these failures easy to detect.

### Why pointer-only CAS would be a regression

A tempting rewrite is a conventional compare-and-swap loop:

```text
read head A
read A.next B
CAS(head, expected=A, desired=B)
```

Now begin with `A -> B -> C`. An interrupted allocator remembers A and B. Another context removes A, removes B, and returns A, leaving `A -> C` while B remains leased. Comparing only the head address succeeds: it is A again. Installing the remembered B resurrects a leased block into the free list. A later allocation can hand out B a second time.

The original implementation deliberately used load-acquire-exclusive and store-release-exclusive rather than pointer-only CAS. On Cortex-M33, exception boundaries clear the local exclusive monitor, and a failed exclusive store does not perform the write. Exclusive operations also have alignment and memory-region requirements. These facts are described in sections 2.2.8–2.2.9 of the [Cortex-M33 Devices Generic User Guide](https://documentation-service.arm.com/static/66be2153882fec713ef49e49).

For this pool's single-core, exception-driven interleaving, resuming with an invalidated reservation prevents the stale head update even if the head's numerical value has returned to A. That is a useful architectural advantage. A new backend for another core, a scheduler that switches contexts differently, or participation by another bus master needs its own argument.

### The assembly contract was incomplete

The previous store declared the modified head as an input-only operand:

```cpp
asm("stlex %0, %1, %2"
    : "=&r"(failed)
    : "r"(new_head), "Q"(head_)
    : "memory");
```

The corrected form describes the write and preserves the instruction's side effects:

```cpp
asm volatile("stlex %0, %2, %1"
    : "=&r"(failed), "=Q"(head_)
    : "r"(new_head)
    : "memory");
```

GCC requires modified operands to be represented as outputs or appropriately tied operands; a general memory clobber does not correct an input-only declaration. `volatile` also prevents treating a side-effecting assembly operation as a dispensable calculation. These are compiler requirements, separate from hardware memory ordering. [GCC extended assembly documentation](https://gcc.gnu.org/onlinedocs/gcc/Extended-Asm.html).

The current load-exclusive operations are volatile too. The store's operand pattern follows [ARM's CMSIS implementation](https://github.com/ARM-software/CMSIS_5/blob/develop/CMSIS/Core/Include/cmsis_gcc.h). This repair is necessary even if the previous compiler happened to emit satisfactory instructions in the tested build; no concrete miscompilation of the original firmware was demonstrated.

The cleanup also explicitly constructs the free-list pointer when reclaiming storage. `CLREX` clears an abandoned reservation on the empty-pool path. The latter is reservation hygiene, not evidence that the previous empty path had corrupted the pool. Explicit zero initialization of counters improves clarity; the original C++23 atomic default initialization should not be described as an uninitialized-counter bug.

### A remaining issue: the read before the failed store

The deeper review exposes a boundary that the recent fixes do **not** close. Allocation currently includes an ordinary C++ typed read:

```cpp
Block *const new_head = *old_head->next();
```

Consider this different interruption point:

1. A task executes `LDAEX` and obtains block A.
2. Before it reads A's link, an ISR allocates A and constructs a payload there.
3. The ISR retains A and returns.
4. The task reads the former link location as a `Block*` object.
5. Its eventual `STLEX` fails because preemption cleared the reservation.

At the machine level, the read may just load an aligned word of payload bytes that is subsequently discarded. At the C++ level, the storage no longer contains the free-list pointer object being read. Preventing the eventual head update does not retrospectively justify that typed access. The lifetime restriction is independent of whether the processor can load those bytes without fault. See [C++ object lifetime](https://eel.is/c++draft/basic.life).

This is an unresolved safety argument in the current implementation, not a newly reproduced hardware crash. The pool should not yet be described as fully validated for arbitrary payloads under preemption. Specializing for one MCU is a reasonable way to close this boundary, but merely saying “single core” does not close it.

Three proposed solutions deserve comparison:

**An audited machine-word backend.** Put the speculative link load and exclusive head update in an explicitly supported assembly implementation. Keep the candidate link as raw register bits until success; a failed attempt must not dereference those bits or interpret them through a live C++ pointer object. The old block address remains readable, aligned SRAM for the pool's lifetime. This can retain the overlay's zero extra link storage, but requires an exact ABI, stable memory permissions, no external metadata writers, correct constraints, and examination of generated code. This is a proposal, not a supplied or proven implementation.

**Permanently live metadata.** Store a link or index separately from the payload, keeping its lifetime independent of payload reuse. Use atomic metadata accesses if making a C++ concurrent-access claim. This spends roughly a word per block before alignment effects, but makes the lifetime argument simpler. It still needs ABA protection; separating metadata does not make pointer-only CAS correct.

**A short interrupt-masked metadata operation.** Prevent every participating context from interleaving while the head and link are accessed. Perform payload construction and destruction outside that interval. This avoids exclusive retries and the speculative overlay read, but spends interrupt latency and requires an exact masking policy.

The first option most directly preserves the original design's memory efficiency. The third is an essential performance baseline. The second may be preferable when auditability or additional supported environments justify the storage cost.

## 5. Deferred logging is an ownership problem too

### Layout must describe the object that is actually stored

The previous `ReferenceHolder` calculated offsets from `Ts...`, then constructed `std::decay_t<Ts>`. Array arguments make that difference observable. Consider:

```cpp
const char text[] = "a";
holder.Store(uint8_t{7}, text, uint8_t{9});
```

On the current 32-bit pointer ABI, the old layout treats `text` as a two-byte character array, while construction stores a four-byte pointer.

| Stored argument | Previous offset | Correct offset | Actual stored size |
|---|---:|---:|---:|
| First byte | 0 | 0 | 1 |
| Pointer obtained by array decay | 1 | 4 | 4 |
| Final byte | 3 | 8 | 1 |

The pointer is misaligned and overlaps the final byte. On a target that tolerates some unaligned machine accesses, the overlap still corrupts its value, and the language alignment requirement remains. Host reproductions exposed both corrupted pointer values and a UBSan alignment error; the table above is the corresponding target-layout analysis, not a report of running that failure on the board.

The current implementation uses decayed types consistently for both storage and retrieval. It also gives an empty argument list size zero and alignment one. Without that case, a simple `Log("started")` instantiated `Layout<>` and indexed an empty offsets array during constant evaluation.

These fixes have little inherent runtime cost. Offsets and capacity checks are compile-time quantities. Correct alignment can even produce better instructions than an accidentally unaligned representation.

### A trivial destructor does not make byte copying safe

The old holder permitted a stored object with a trivial destructor but a meaningful copy constructor. For example:

```cpp
struct AddressAware {
  AddressAware() noexcept : self(this) {}
  AddressAware(const AddressAware&) noexcept : self(this) {}
  const AddressAware *self;
};
```

Copying the holder's byte array does not invoke `AddressAware`'s copy constructor. The copied `self` still points at the previous instance. When the old logging path created a temporary entry and assigned it into a node, this was exactly the sort of hidden copy the abstraction needed to account for.

The current holder is noncopyable and nonmovable. The queue constructs `LogEntry` directly in its final location, and argument construction happens there once. This preserves address-sensitive values without adding type-erased copy callbacks or heap ownership.

An alternative would permit only suitably constrained, trivially copyable argument representations. That restriction could support compact copying between stages. It would be a different contract and would still require correct destination lifetimes and character ownership. It should not be inferred from trivial destruction alone.

### Borrowing is still borrowing

The current logger stores scalar arguments by value, but pointer and view arguments refer to somebody else's storage:

```cpp
void Report() {
  char label[] = "ready";
  (void)logger.Log("state={}", label);
}  // label dies; formatting may happen much later.
```

This remains invalid usage. Copying a `string_view` would not help, and release/acquire ordering cannot extend the lifetime of its characters. A buffer that remains alive but changes before formatting can produce the wrong message or introduce an unsynchronized access.

The current API documents the borrowing requirement. It does not enforce it. String literals satisfy the requirement, but accepting `const char (&)[N]` does not prove that an argument is a literal: a local array can have that type too.

A proposed faster and safer restricted logger would use literal format strings, numeric arguments, and explicit fixed-capacity owned text. Copying a short character buffer at enqueue time increases producer work but makes ownership self-contained. A separate borrowed-text operation could remain for demonstrably persistent storage. A wrapper named `StaticText` would only be a promise unless its construction mechanism actually establishes static lifetime; a compile-time string parameter can provide a stronger design.

The current cleanup also preserves invalid runtime-format errors and counts queue-full drops. Supporting arbitrary runtime formats has a cost: validation may occur while preparing the entry and again in the consumer formatting path. Restricting format selection to compile-time event definitions could remove repeated work, provided the chosen formatting API preserves validation. That is worth measuring after the primitive's safety contract is settled.

## 6. What the safety repairs cost

### Concrete sizes on the selected ABI

To make the memory tradeoff explicit, small `sizeof` probe functions were compiled with the actual Arm GNU 13.2.1 compiler and the repository's Cortex-M33 hard-float flags. The resulting immediate constants give these sizes:

| Representation | Bytes |
|---|---:|
| Current `LogEntry`, alignment 8 | 88 |
| Node shaped as `uint32_t data; atomic<Node*> next;` | 8 |
| Node shaped as `optional<uint32_t> data; atomic<Node*> next;` | 12 |
| Old node shape holding the **current** `LogEntry` | 96 |
| Optional node shape holding the current `LogEntry` | 104 |
| Current `MpscQueue<uint32_t, 16>` | 236 |
| Current `MpscQueue<LogEntry, 16>` | 1,800 |
| Current `MemoryPool<uint32_t, 16>` | 88 |
| Pool debug counters, including when `Debug == false` | 20 |

The shape comparison holds the payload constant. It is not a comparison of complete historical logger binaries, because the payload representation changed too. It also says nothing about cycle counts.

With 17 nodes for a capacity-16 queue, the optional representation adds 68 bytes for the integer example and 136 bytes for the current log-entry example relative to the corresponding direct-payload node shapes. Padding makes the cost larger than a single byte per node.

The current optional representation is a straightforward correctness baseline. It is not the only way to achieve correct object lifetimes.

### Replacing a per-node flag with a queue invariant

Only the initial sentinel lacks a payload. Every producer-created node has one. The consumer alone controls destruction of the retained head. These facts suggest a proposed representation:

- Each node contains an atomic link and aligned raw payload storage.
- Producers explicitly construct `T` before publishing a node.
- One consumer-owned flag records whether the current head contains a live payload.
- Advancing past the initial sentinel skips payload destruction; every subsequent retired head destroys its payload.

This can move engagement state from every node into the queue. For trivially destructible payloads, payload destruction requires no runtime action. For general nothrow payloads, exactly-once destruction still has to be preserved.

The existing nonmovable-payload, final-head, exhaustion, and ownership tests should remain unchanged as behavioral requirements. Add representation-size checks and target assembly inspection. Do not obtain the memory saving by restoring assignment into unconstructed storage. A separate link-only sentinel is another option, but changing the node/reclamation arrangement deserves its own algorithm review.

### Remove diagnostics that are supposed to be disabled

`Debug == false` currently removes counter updates with `if constexpr`, but the five atomic counter members still occupy 20 bytes in every pool. An empty disabled-counter policy, stored with `[[no_unique_address]]` where appropriate, can remove that storage. The debug accessor should then be constrained or otherwise explicitly unavailable when counters are disabled.

Enabled counters currently use default sequentially consistent increments. If they are only statistical observations, relaxed increments can express the necessary semantics without imposing an unrelated global ordering. Individual counters remain atomic; a collection of reads is not a coherent snapshot. Keep all instrumentation outside the exclusive reservation interval so it does not interfere with the operation it measures.

Similarly, the logger's dropped-entry counter performs an atomic read-modify-write on overload. A logger restricted to one producing context could use a cheaper ownership scheme for statistics, provided task reads are still synchronized. Diagnostics should be measured under overload, when their cost is easiest to overlook.

### Explicit ownership can have a small representation cost

The pool's `UniquePtr` deleter remembers the originating pool. On a conventional 32-bit ABI, a data pointer plus a pool pointer can occupy two words. A statically bound pool handle or a slot index can sometimes reduce that, at the cost of restricting which pool owns the object and how handles are resolved.

That optimization should follow evidence that handles are numerous or frequently copied. Removing ownership information without replacing its invariant merely makes wrong-pool releases easier. For a queue that retains payloads in place, `emplace()` already avoids many transfers without weakening ownership.

## 7. Choosing a narrower primitive

### One producer and one consumer can remove the allocator

A ring of packet descriptors is often a better candidate for a fixed radio path than a general node queue. If one execution context writes and one reads, each context owns one index. The producer publishes initialized slots through its write index; the consumer publishes reusable slots through its read index. Appropriate acquire/release operations establish both directions of ownership transfer.

This can eliminate the shared free list, per-node links, and producer atomic exchange. A ring with one permanently unused slot gives a simple full/empty distinction. A sequence-counter design can use all slots, but its capacity and wraparound argument must be explicit.

The restriction is stronger than “one function writes.” A task and an ISR calling that function are two producers. Two nesting ISRs are two producers. Giving each ISR its own ring is an alternative, with a merging task as consumer. That sacrifices a single global FIFO order unless an explicit merging policy supplies one.

For a particularly small implementation, accept only fixed-size descriptor values with bounded copy cost and trivial destruction. For a richer ring, an in-place slot protocol can support nonmovable objects, but full/empty and lifetime tests become correspondingly more involved. A borrow from a slot must delay publishing that slot as reusable until consumption finishes.

No ring should overwrite unread data as an accidental overflow policy. Drop-newest, drop-oldest, retry, and backpressure are different APIs with different synchronization requirements. Start with a clear failure result and a counter.

### A short critical section is a legitimate competitor

On a single core, saving the previous interrupt mask, masking all participating interrupts, updating a few metadata words, and restoring the mask can outperform a retrying atomic operation. It also offers a more direct bound on interference imposed on other interrupts. This is a hypothesis to benchmark for this target, not a measured result.

The existing guard saves and restores `PRIMASK`; the cleanup made its entry assembly volatile. Restoring the previous value preserves callers that were already masked. Its memory clobbers constrain compiler movement across the protected region. None of this makes an arbitrary callback short: `CriticalSection()` currently accepts any nothrow callable, including one that waits or performs substantial work.

Keep constructors, destructors, logging, and peripheral waits out of a proposed allocator metadata critical section. Establish exclusive ownership under the mask, then perform payload work after restoring it. For release, finish payload destruction before publishing the block as free.

The mask must cover every accessor. A FreeRTOS critical section based on a priority threshold is not interchangeable with masking all configurable interrupts. In this repository, the timer producer runs at priority level 0 while the maximum syscall priority corresponds to level 2. A task's RTOS critical section cannot be assumed to exclude that producer. The relevant values are visible in [FreeRTOSConfig.h](../src/FreeRTOSConfig.h) and [main.cc](../src/main.cc).

NMI/fault participation and DMA remain outside the intended contract. A primitive shared with those contexts needs a separate design. Favor a precisely stated exclusion over an expansive “safe from any context” comment.

### The tradeoff table

The following alternatives are proposals to evaluate; the table does not imply that all are implemented.

| Design | Restriction that buys simplicity | Potential benefit | Main obligation |
|---|---|---|---|
| Current MPSC shape with repaired lifetimes | One consumer; producers finish publication; weak unavailable result | In-place payloads; multiple producers | Close pool proof boundary; test publication gaps |
| ISR-producer/task-consumer MPSC | No runtime task producers or ISR consumer | Task cannot observe an active ISR's publication hole | Enforce topology and test nesting |
| SPSC descriptor ring | Exactly one producer context and one consumer | No shared allocator or link exchange | Slot ownership, overflow, index wrap |
| One SPSC ring per producer | Fixed producer set; merge semantics accepted | Isolated contention and predictable producer work | Fair draining and ordering policy |
| Overlay pool with audited ARM backend | Exact core, compiler ABI, memory, scheduler | No separate per-block link storage | Full machine-level and compiler argument |
| Pool with permanent metadata | Additional link storage accepted | Simpler payload-lifetime separation | Atomic access and ABA protection still required |
| Interrupt-masked pool | Every accessor is covered by the mask | Short fixed metadata path, no retries | Measured masking duration and priority policy |
| Trivial-payload specialization | Bounded simple values only | Fewer lifetime branches and metadata | Reject unsupported types; preserve publication |

## 8. Tests that make the restrictions credible

### What has already been tested

The cleanup added three host suites and an ARM compile target:

| Target | Existing evidence | What it does not establish |
|---|---|---|
| `storage_test` | Empty packs, decayed array layout, alignment, value snapshots, address-aware construction, reuse | Target interrupt behavior |
| `log_entry_test` | Empty/mixed deferred formatting, borrowed data while alive, invalid format and small-buffer errors | Safe lifetime of arbitrary caller-owned text |
| `mpsc_queue_test` | FIFO/reuse, exhaustion, zero capacity, nonmovable and owning payloads, exact destruction and sentinel release | Concurrent publication or the ARM allocator |
| `memory_pool_compile_test` | Actual ARM pool/queue instantiation, debug paths and nonmovable payloads compile | Runtime correctness, progress, or latency |
| `hardware_test` | Two CC1354P10 boards: real ARM pool lifetimes, queue capacity/FIFO, deferred formatting, and 30,000 ordered/checksummed records from two tasks plus an ISR on each board | Exhaustive interruption schedules, the speculative-read lifetime proof, or comparative performance |

The host queue tests intentionally use a sequential test allocator. That lets them isolate the queue's lifecycle obligations; it cannot validate the pool's exclusive monitor. ASan and UBSan passed for the host suites, but neither instrument executes the real ARM allocator in those tests.

The hardware tests added later do execute the production allocator, including concurrent task and interrupt use. Both boards passed after explicit hardware resets. The runner discards UART data from the prior firmware before releasing reset, so a previous run cannot supply its success marker. [Hardware instructions and results](hardware_tests.md) describe the workload and its limits. This is useful evidence that the implementation operates on the intended core; it does not close the speculative-read proof boundary or replace forced-interleaving tests.

Hardware testing also exposed a resource constraint outside the queue itself. The demo's logging task reserved 800 bytes of stack, while its compiled integer-formatting call chain used at least 816 bytes before exception and scheduler context. Its startup literal printed, but subsequent integer logs stopped. Raising the task stack to 2 KiB restored sustained logging on both boards. Deferring formatting out of the ISR reduces interrupt work, but the consumer must still have enough stack for the formatter's deepest call chain.

The firmware build also passes and its inspected ELF has no unresolved symbols or heap/exit-registration machinery. The small runtime hooks preserve local RAII destruction while deliberately declining global destructor registration for this reset-only firmware. That policy belongs in [stubs.cc](../src/stubs.cc); it must not be used as an excuse to omit local queue or payload destruction.

The existing checks can be reproduced from the repository root:

```sh
bazel build --config=m33 //src/...
bazel test //src:storage_test //src:log_entry_test //src:mpsc_queue_test
bazel test --copt=-fsanitize=address,undefined \
  --linkopt=-fsanitize=address,undefined \
  //src:storage_test //src:log_entry_test //src:mpsc_queue_test
```

### Force the dangerous schedules on the actual core

The next tests should control interruption points rather than merely create traffic and hope to hit them.

For the pool, force an exception **after the exclusive head load but before the speculative link load**. In the ISR, allocate that same block and retain a live payload with a recognizable first word. When the task resumes, verify that it retries, does not allocate the ISR-owned block, and never installs payload bits as the head. This exposes the exact hardware path discussed earlier; passing it alone still does not settle the C++ lifetime argument.

Separately, interrupt **after the link has been read** and perform the A/B/A sequence. The first store-exclusive must fail, and no address may be leased to two owners. Track a set or bitmap of live allocations in the test harness, outside the reservation sequence.

Exercise nested IRQs, PendSV-driven task switches, empty and full pools, capacities zero and one, repeated exhaustion/recovery, and over-aligned payloads. Include the intended memory region and security configuration. An unsupported configuration that makes exclusive stores fail forever needs a detectable failure in qualification, not an unexplained application hang.

Instrumentation requires care. A callback inserted inside an exclusive sequence can itself execute instructions that consume the reservation or change scheduling. Use an intentionally designed test backend or hardware-triggered interruption, then record results after the store-exclusive or `CLREX`. Inspect the instrumented instructions as well as the production instructions.

For the queue, suspend A precisely between tail exchange and link publication, let B finish, and call dequeue. Check the documented unavailable result, then resume A and check A-before-B delivery. Also test a consumer wakeup protocol: observing an unavailable entry must not result in sleeping forever after the remaining publication. The current periodic polling example avoids needing such a notification protocol, but a future event-driven consumer must supply one.

### Make invalid use fail early

Proposed compile-time checks and negative compilation tests should cover oversized or over-aligned argument packs, throwing payload operations, forbidden holder copying, unsupported core/ABI combinations, and any trivial-payload specialization. A negative test must fail for the intended diagnostic, not merely because a dependency is missing.

The pool's `create()` and `allocate()` still have unconditional `noexcept` without the queue's corresponding nothrow type constraints. Constraining those operations is a sensible follow-up for the supported payload policy. A nothrow trait cannot prove the absence of blocking, allocation, peripheral access, or excessive work; those require a restricted API and review.

For ownership restrictions, debug tests should reject wrong-pool releases, double releases, and use of an ISR-only operation from a task. Most execution-topology properties cannot be proven by ordinary C++ type traits. Distinct endpoint objects, limited visibility, context checks, and target integration tests work together.

For owned logging text, deliberately destroy or overwrite the producer's original buffer before formatting and verify that the recorded message survives. The current borrowed API cannot pass that test legitimately; it belongs to a proposed owning representation. Keep that distinction visible in test names and documentation.

### Measure the supported binary

Measure the release compiler and flags actually used on the board. Include the full enqueue/dequeue paths, not just the atomic exchange. Record empty/full paths, slot recycling, ordinary load, nested interrupts, and overload. Measure diagnostics enabled and disabled separately.

Use a cycle counter where supported or the board timer, and GPIO instrumentation when external timing is useful. Account for measurement overhead and timer wrap. Report sample counts and interrupt load with the results. An observed maximum is not a proven bound; a bound must include allowed higher-priority interference and payload work.

Assembly checks should verify the intended head load/store sequence, absence of helper calls in a specialized reservation window, no unexpected library locking, and expected access widths. Run these for each claimed supported optimization mode, including LTO only if LTO is supported. A compiler upgrade should trigger this qualification again. RAM-size assertions can protect a chosen representation budget without pretending to prove timing.

## 9. A practical order for the next refinements

The cleanup establishes a useful behavioral baseline: objects are constructed and destroyed deliberately, deferred storage keeps stable addresses, and the public comments describe weaker queue availability and borrowed data honestly. These repairs should remain while representation choices are measured.

First, close the pool's speculative-read proof boundary. For this project's stated priorities, compare a small audited ARM backend against a narrowly masked free-list operation. Keep permanent metadata as the simpler alternative if its RAM cost is acceptable. Do not substitute a pointer-only CAS stack.

Second, write down each real producer/consumer relationship. A logging queue and a radio packet path need not use the same primitive. The current ISR-to-task logger can exploit its restricted topology. A future radio descriptor path may qualify for an SPSC ring and avoid allocation entirely.

Third, remove overhead that serves no supported use case: disabled debug-counter storage, unnecessary argument moves, repeated format validation where formats are static, and per-node engagement state when a queue-level invariant suffices. Preserve the same behavioral tests while changing representations.

Finally, choose a character-ownership policy for deferred logs. If arbitrary transient text is unnecessary, exclude it. If it is useful, copy it into a bounded representation and measure that explicit cost. The resulting API should make the efficient, supported path easy to use and the unsupported path difficult to express.

The desired result is a small set of primitives with narrow, executable contracts: a stated machine, a stated ownership model, a stated scheduling model, and measurements of the code that implements them. That is a stronger basis for performance than either universal portability or an unqualified claim of lock freedom.
