# GPU Page Fault Handler Concurrency Analysis

## Overview

The NVIDIA UVM driver handles GPU page faults through two main mechanisms:
1. **Replayable faults** - Originate from Graphics Engine (SM), use "fault and stall" mechanism
2. **Non-replayable faults** - Originate from Copy Engine (CE) and PBDMA engines, use "fault and switch" mechanism

## Lock Hierarchy

Based on `uvm_lock.h`, the lock ordering is:
1. `UVM_LOCK_ORDER_ISR` - GPU ISR service locks (highest priority for fault handling)
2. `UVM_LOCK_ORDER_VA_SPACE` - VA space reader/writer lock
3. `UVM_LOCK_ORDER_VA_BLOCK` - Per-VA-block mutex

## Replayable Fault Handler Concurrency

### Entry Point
- **Function**: `uvm_parent_gpu_service_replayable_faults()` in `uvm_gpu_replayable_faults.c`
- **Called from**: ISR bottom-half (workqueue context)

### Lock Acquisition Sequence

1. **ISR Service Lock** (`parent_gpu->isr.replayable_faults.service_lock`)
   - **Type**: Semaphore (uvm_semaphore_t)
   - **Acquisition**: Taken in ISR top-half, transferred to bottom-half
   - **Purpose**: Serializes fault buffer access and prevents interrupt storms
   - **Bottleneck**: **CRITICAL** - This is a per-GPU exclusive lock. Only ONE bottom-half can process replayable faults at a time per GPU.

2. **VA Space Lock** (`va_space->lock`)
   - **Type**: Reader/writer semaphore (rw_semaphore)
   - **Acquisition**: Taken in READ mode during `service_fault_batch()`
   - **Purpose**: Protects VA space data structures (VA ranges, GPU VA spaces)
   - **Bottleneck**: **MODERATE** - Multiple fault handlers can hold read locks concurrently, but writers block all readers

3. **mmap_lock** (`mm->mmap_lock`)
   - **Type**: Reader/writer semaphore
   - **Acquisition**: Taken when `mm` is available (for ATS/HMM faults)
   - **Purpose**: Protects VMA structures
   - **Bottleneck**: **MODERATE** - Can conflict with CPU page faults and mmap operations

4. **VA Block Lock** (`va_block->lock`)
   - **Type**: Mutex
   - **Acquisition**: Taken per VA block in `service_fault_batch_block()`
   - **Purpose**: Protects page table mappings and GPU work tracker for a specific VA block
   - **Bottleneck**: **LOW** - Fine-grained locking per 2MB VA block, allows parallel processing of different blocks

### Processing Flow

```
uvm_parent_gpu_service_replayable_faults()
  └─> [Holds: ISR service_lock]
      └─> fetch_fault_buffer_entries() - Read GET/PUT pointers
      └─> preprocess_fault_batch() - Parse and coalesce faults
      └─> service_fault_batch()
          └─> [Acquires: VA space lock (read)]
              └─> [Acquires: mmap_lock (read) if mm available]
                  └─> service_fault_batch_dispatch()
                      └─> service_fault_batch_block()
                          └─> [Acquires: VA block lock]
                              └─> uvm_va_block_service_locked()
                                  └─> [May acquire: Page tree locks, PMM locks]
```

## Non-Replayable Fault Handler Concurrency

### Entry Point
- **Function**: `uvm_parent_gpu_service_non_replayable_fault_buffer()` in `uvm_gpu_non_replayable_faults.c`
- **Called from**: ISR bottom-half (workqueue context)

### Lock Acquisition Sequence

1. **ISR Service Lock** (`parent_gpu->isr.non_replayable_faults.service_lock`)
   - **Type**: Semaphore (uvm_semaphore_t)
   - **Acquisition**: Taken in bottom-half via `uvm_parent_gpu_non_replayable_faults_isr_lock()`
   - **Purpose**: Serializes non-replayable fault processing per GPU
   - **Bottleneck**: **CRITICAL** - Per-GPU exclusive lock. Multiple bottom-halves can be scheduled but serialize on this lock.

2. **VA Space Lock** (`va_space->lock`)
   - **Type**: Reader/writer semaphore
   - **Acquisition**: Taken in READ mode in `service_fault_once()`
   - **Purpose**: Protects VA space structures
   - **Bottleneck**: **MODERATE** - Same as replayable faults

3. **mmap_lock** (`mm->mmap_lock`)
   - **Type**: Reader/writer semaphore
   - **Acquisition**: Taken when `mm` is available
   - **Bottleneck**: **MODERATE** - Same as replayable faults

4. **VA Block Lock** (`va_block->lock`)
   - **Type**: Mutex
   - **Acquisition**: Taken per fault in `service_managed_fault_in_block()`
   - **Purpose**: Protects VA block state
   - **Bottleneck**: **LOW** - Fine-grained per block

### Processing Flow

```
uvm_parent_gpu_service_non_replayable_fault_buffer()
  └─> [Holds: ISR service_lock]
      └─> fetch_non_replayable_fault_buffer_entries() - Read from RM shadow buffer
      └─> For each fault:
          └─> service_fault()
              └─> service_fault_once()
                  └─> [Acquires: VA space lock (read)]
                      └─> [Acquires: mmap_lock (read) if mm available]
                          └─> service_managed_fault_in_block()
                              └─> [Acquires: VA block lock]
                                  └─> uvm_va_block_service_locked()
```

## Key Bottlenecks

### 1. **ISR Service Lock (CRITICAL BOTTLENECK)**

**Impact**: **HIGHEST**

#### Understanding the ISR Lock Behavior

**Important Clarification**: The ISR service lock does NOT mean you process only one fault at a time. Instead:

1. **Lock Granularity**: The lock serializes the **fault handler execution** (bottom-half function), not individual faults
2. **Batching**: Within a single handler execution, multiple **batches** of faults are processed:
   - Each batch can contain up to **256 faults** (configurable via `uvm_perf_fault_batch_count`)
   - Up to **20 batches** can be processed per handler execution (configurable via `uvm_perf_fault_max_batches_per_service`)
   - This means up to **5,120 faults** can be processed in a single handler execution!

3. **Handler Serialization**: Only **ONE bottom-half handler** can execute at a time per GPU, even though:
   - Multiple interrupts can arrive
   - Multiple bottom-halves can be scheduled to the workqueue
   - But they all serialize on the ISR service lock

#### Replayable Faults ISR Lock

- **Lock**: `parent_gpu->isr.replayable_faults.service_lock` (semaphore)
- **Acquisition**: Taken in ISR top-half using `down_trylock()`, then "transferred" to bottom-half
- **Purpose**: 
  - Prevents interrupt storms (disables interrupts while processing)
  - Serializes fault buffer access (GET/PUT pointer updates)
  - Ensures atomic fault processing batches
  
- **Processing Flow**:
  ```
  ISR Top-Half (interrupt context)
    └─> down_trylock(service_lock)  [Acquires lock]
    └─> Disable interrupts
    └─> Schedule bottom-half
    └─> [Lock ownership transferred to bottom-half]
  
  Bottom-Half (workqueue context)
    └─> [Already holds service_lock]
    └─> uvm_parent_gpu_service_replayable_faults()
        └─> while (batches < max_batches):
            └─> fetch_fault_buffer_entries()  [Reads up to 256 faults]
            └─> preprocess_fault_batch()      [Coalesces duplicates]
            └─> service_fault_batch()         [Processes all faults in batch]
            └─> [Repeat for next batch]
    └─> Unlock service_lock
    └─> Re-enable interrupts
  ```

- **What Happens When Multiple Interrupts Arrive**:
  - First interrupt: Top-half acquires lock, schedules bottom-half
  - Subsequent interrupts: Top-half sees lock held, **cannot schedule another bottom-half**
  - New faults accumulate in hardware buffer while first handler processes
  - After first handler completes and unlocks, interrupts are re-enabled
  - If faults still pending, next interrupt will schedule another bottom-half

#### Non-Replayable Faults ISR Lock

- **Lock**: `parent_gpu->isr.non_replayable_faults.service_lock` (semaphore)
- **Acquisition**: Taken in bottom-half (not top-half, since RM manages the buffer)
- **Purpose**: Serializes access to RM's shadow buffer
- **Key Difference**: Multiple bottom-halves CAN be scheduled, but they serialize on the lock:
  ```c
  // From uvm_gpu_isr.c:145
  scheduled = nv_kthread_q_schedule_q_item(&parent_gpu->isr.bottom_half_q,
                                           &parent_gpu->isr.non_replayable_faults.bottom_half_q_item);
  // If already queued, the existing instance will handle pending faults
  ```
  
- **Processing Flow**:
  ```
  ISR Top-Half (interrupt context)
    └─> [No lock acquisition - RM owns buffer]
    └─> Schedule bottom-half (can schedule multiple times)
  
  Bottom-Half (workqueue context)
    └─> uvm_parent_gpu_non_replayable_faults_isr_lock()  [Acquires lock]
    └─> uvm_parent_gpu_service_non_replayable_fault_buffer()
        └─> do {
                └─> fetch_non_replayable_fault_buffer_entries()  [Reads from RM shadow buffer]
                └─> For each fault:
                    └─> service_fault()  [Processes individually]
            } while (cached_faults > 0)
    └─> Unlock service_lock
  ```

#### Why It's a Bottleneck

1. **Complete Serialization Per GPU**:
   - All fault processing for a GPU happens sequentially
   - Cannot leverage multiple CPUs to process faults in parallel for the same GPU
   - Even though batching processes many faults, it's still one-at-a-time handler execution

2. **Long Critical Section**:
   - Lock held during entire handler execution
   - Includes: fault fetching, parsing, VA space lookups, VA block servicing, GPU work submission, TLB invalidations
   - Can hold lock for milliseconds while processing thousands of faults

3. **Interrupt Disabling**:
   - For replayable faults, interrupts are disabled while lock is held
   - New faults accumulate but cannot trigger new handler until lock released
   - Can cause latency spikes if handler takes too long

4. **Workqueue Serialization**:
   - Even though workqueue can run on multiple CPUs
   - ISR lock ensures only one handler executes at a time per GPU
   - Other CPUs wait for lock, reducing parallelism

#### Mitigation Attempts

1. **Batching**:
   - Processes up to 256 faults per batch (reduces lock acquisition overhead)
   - Processes up to 20 batches per handler execution
   - But still serialized by ISR lock

2. **VA Block-Level Locking**:
   - Allows parallel processing of different VA blocks within a batch
   - But ISR lock still serializes batch processing

3. **Coalescing**:
   - Merges duplicate faults on same page
   - Reduces number of faults to process
   - But doesn't reduce lock hold time significantly

#### Performance Impact

**Under Light Load**:
- Lock contention is minimal
- Handler completes quickly
- Next interrupt can schedule immediately after unlock

**Under Heavy Load**:
- Handler processes many batches (up to 20)
- Lock held for extended periods (milliseconds)
- New interrupts arrive but cannot schedule handlers
- Faults accumulate in hardware buffer
- Can cause:
  - Increased fault latency
  - Buffer overflow (if buffer fills up)
  - GPU stalls waiting for faults to be serviced

### 2. **VA Space Lock Contention (MODERATE BOTTLENECK)**

**Impact**: **MODERATE**

- Taken in READ mode by fault handlers
- Writers (mmap, munmap, permission changes) block all readers
- Multiple readers can proceed concurrently
- However, fault handlers may hold this lock for extended periods while:
  - Processing multiple faults in a batch
  - Waiting for GPU work completion
  - Performing migrations

**Why it's a bottleneck**:
- Long-held read locks can delay writers
- Writers can block fault processing
- Fair rw_semaphore implementation means pending writers block new readers

**Mitigation**:
- Writer serialization lock (`serialize_writers_lock`) prevents deadlocks
- Read-acquire-write-release lock prevents interleaving issues
- But contention still exists under heavy load

### 3. **mmap_lock Contention (MODERATE BOTTLENECK)**

**Impact**: **MODERATE**

- Required for ATS/HMM fault handling
- Can conflict with:
  - CPU page faults
  - mmap/munmap operations
  - Other kernel operations requiring mmap_lock

**Why it's a bottleneck**:
- Kernel-wide contention point
- Fault handlers may hold it during migrations
- Can cause delays in both GPU and CPU fault handling

### 4. **VA Block Lock (LOW BOTTLENECK)**

**Impact**: **LOW**

- Fine-grained: one lock per 2MB VA block
- Allows parallel processing of different blocks
- Only serializes operations on the same block

**Why it's NOT a major bottleneck**:
- High granularity reduces contention
- Different faults on different blocks can proceed in parallel
- Lock is held only during block-specific operations

## Detailed Answer: Can You Process Only One Fault at a Time?

### Short Answer
**No, you don't process one fault at a time. You process batches of faults (up to 256 per batch, up to 20 batches = 5,120 faults per handler execution), but only ONE handler execution can run at a time per GPU due to the ISR lock.**

### Detailed Explanation

#### What the ISR Lock Actually Serializes

The ISR service lock serializes the **fault handler function execution**, not individual fault processing. Here's what actually happens:

**Scenario: 10,000 faults arrive on GPU 0**

1. **First Interrupt Arrives**:
   - ISR top-half acquires `service_lock` (via `down_trylock()`)
   - Disables replayable fault interrupts
   - Schedules bottom-half to workqueue
   - **Lock ownership transferred to bottom-half**

2. **Bottom-Half Executes** (holds `service_lock`):
   - Processes **Batch 1**: Fetches up to 256 faults, processes them
   - Processes **Batch 2**: Fetches next 256 faults, processes them
   - ... continues up to 20 batches ...
   - Processes **Batch 20**: Fetches final batch, processes them
   - **Total: Up to 5,120 faults processed in this handler execution**
   - Releases `service_lock`
   - Re-enables interrupts

3. **More Faults Still Pending**:
   - Hardware buffer still has ~4,880 faults
   - Interrupt fires again
   - New bottom-half scheduled
   - **Waits for lock** (if previous handler still running)
   - Once lock acquired, processes next batches

#### Concrete Example: Processing 10,000 Faults

```
Time    | CPU 0                    | CPU 1                    | GPU Buffer
--------|--------------------------|--------------------------|------------
T0      | Handler 1 starts         | [Waiting for lock]      | 10,000 faults
        | Lock: HELD               |                          |
T1      | Processing batch 1       | [Waiting for lock]      | 10,000 faults
        | (256 faults)             |                          |
T2      | Processing batch 2       | [Waiting for lock]      | 10,000 faults
        | (256 faults)             |                          |
...     | ...                      | ...                      | ...
T20     | Processing batch 20      | [Waiting for lock]      | 4,880 faults
        | (256 faults)             |                          |
T21     | Handler 1 completes     | Handler 2 starts         | 4,880 faults
        | Lock: RELEASED           | Lock: ACQUIRED           |
T22     | [Idle]                   | Processing batch 1       | 4,880 faults
        |                          | (256 faults)             |
...     | ...                      | ...                      | ...
```

**Key Observations**:
- Only ONE handler executes at a time (serialized by ISR lock)
- Each handler processes MANY faults (up to 5,120)
- CPU 1 waits for CPU 0 to finish, even though CPU 1 could process different faults
- This is the bottleneck: cannot parallelize across CPUs for same GPU

#### What Happens with Multiple Interrupts

**Replayable Faults**:
```c
// From uvm_gpu_isr.c:100
if (down_trylock(&parent_gpu->isr.replayable_faults.service_lock.sem) != 0)
    return 0;  // Lock already held, cannot schedule another handler
```

- **Interrupt 1**: Acquires lock, schedules handler
- **Interrupt 2**: Sees lock held, **cannot schedule**, returns immediately
- **Interrupt 3**: Sees lock held, **cannot schedule**, returns immediately
- New faults accumulate in hardware buffer
- After handler completes and unlocks, next interrupt can schedule

**Non-Replayable Faults**:
```c
// From uvm_gpu_isr.c:145
scheduled = nv_kthread_q_schedule_q_item(...);
// Can schedule multiple times, but handlers serialize on lock
```

- **Interrupt 1**: Schedules handler 1
- **Interrupt 2**: Can schedule handler 2 (different from replayable!)
- **Handler 1**: Acquires lock, processes faults
- **Handler 2**: Waits for lock, then processes faults
- Multiple handlers can be queued, but execute sequentially

#### Parallelism Within a Batch

Even though handlers serialize, there IS parallelism within a batch:

1. **VA Block Level**: Different VA blocks can be processed in parallel
   - Handler acquires VA space lock (read mode)
   - Processes faults grouped by VA block
   - Each VA block lock allows parallel access to different blocks
   - But still serialized at handler level

2. **GPU Work Submission**: Can submit multiple GPU operations
   - Tracks work in trackers
   - Can overlap GPU operations
   - But handler still holds ISR lock during this

#### The Real Bottleneck

The bottleneck is NOT that you process one fault at a time. The bottleneck is:

1. **Handler Serialization**: Only one handler can execute per GPU
2. **Cannot Parallelize Across CPUs**: Even though faults are independent, they must be processed by one handler
3. **Long Lock Hold Time**: Handler holds lock for entire execution (milliseconds)
4. **Interrupt Disabling**: New interrupts cannot schedule handlers while lock held

#### Comparison: What If There Was No ISR Lock?

**Hypothetical Parallel Processing**:
```
CPU 0: Processing faults 0-255     (batch 1)
CPU 1: Processing faults 256-511 (batch 2)
CPU 2: Processing faults 512-767 (batch 3)
CPU 3: Processing faults 768-1023 (batch 4)
...
```

**Current Serial Processing**:
```
CPU 0: Processing faults 0-5119   (batches 1-20)
CPU 1: [Waiting]
CPU 2: [Waiting]
CPU 3: [Waiting]
```

The ISR lock prevents the parallel scenario, forcing serial execution.

## Concurrency Characteristics

### Parallelism Opportunities

1. **Different GPUs**: Fault handlers for different GPUs can run in parallel (separate ISR locks)
2. **Different VA Spaces**: Faults from different VA spaces can be processed concurrently (separate VA space locks)
3. **Different VA Blocks**: Faults on different VA blocks can be serviced concurrently (separate VA block locks)

### Serialization Points

1. **Same GPU, Replayable Faults**: Serialized by ISR service lock (one handler at a time)
2. **Same GPU, Non-Replayable Faults**: Serialized by ISR service lock (handlers queue and execute sequentially)
3. **Same VA Space**: Multiple readers allowed, but writers block all
4. **Same VA Block**: Fully serialized by VA block lock

## Performance Implications

### Under Light Load
- Bottlenecks are minimal
- ISR lock contention is low
- VA space/block locks provide good parallelism

### Under Heavy Load
- **ISR service lock becomes the primary bottleneck**
  - All fault processing for a GPU serializes
  - Cannot scale across CPUs for the same GPU
  - Batch processing helps but doesn't eliminate serialization
  
- **VA space lock contention increases**
  - Multiple fault handlers compete for read access
  - Writers may be delayed significantly
  - Can cause cascading delays

- **mmap_lock contention**
  - Can delay both GPU and CPU operations
  - Particularly problematic for HMM/ATS workloads

## Recommendations for Optimization

1. **Reduce ISR lock hold time**
   - Move non-critical operations outside the lock
   - Consider finer-grained locking within fault processing
   - Investigate lock-free data structures where possible

2. **Improve VA space lock granularity**
   - Consider per-GPU-VA-space locking instead of per-VA-space
   - Reduce lock hold time during migrations

3. **Optimize batch processing**
   - Tune batch sizes based on workload characteristics
   - Consider adaptive batching based on contention

4. **Consider lock-free fault queuing**
   - Use lock-free queues for fault entries
   - Reduce serialization at the entry point

5. **Parallel fault processing**
   - Allow multiple threads to process faults from the same GPU
   - Use per-uTLB or per-channel locking instead of global ISR lock

## Summary: ISR Lock Impact on Concurrency

### Key Takeaways

1. **You DON'T process one fault at a time**
   - Each handler execution processes **batches** of faults
   - Up to **256 faults per batch**
   - Up to **20 batches per handler execution**
   - **Total: Up to 5,120 faults per handler execution**

2. **You DO serialize handler executions**
   - Only **ONE handler can execute at a time per GPU**
   - Even if multiple CPUs are available
   - Even if faults are independent
   - This is enforced by the ISR service lock

3. **The bottleneck is handler-level serialization, not fault-level**
   - Batching helps amortize lock overhead
   - But cannot parallelize across CPUs for same GPU
   - This limits scalability under heavy fault load

4. **Impact increases with fault rate**
   - Light load: Lock contention minimal, handlers complete quickly
   - Heavy load: Lock held longer, new handlers queue up, faults accumulate
   - Can cause GPU stalls if buffer fills up

### Performance Characteristics

| Metric | Value | Impact |
|--------|-------|--------|
| Faults per batch | Up to 256 | Reduces lock acquisitions |
| Batches per handler | Up to 20 | Amortizes lock overhead |
| Max faults per handler | Up to 5,120 | Good throughput per handler |
| Handlers per GPU | **1 at a time** | **Limits parallelism** |
| CPUs that can help | **0** (for same GPU) | **Cannot scale horizontally** |

### The Fundamental Limitation

The ISR lock creates a **serialization bottleneck** at the handler level:
- Prevents parallel processing across CPUs for the same GPU
- Forces sequential handler execution
- Limits scalability to single-threaded handler performance
- Cannot be overcome by adding more CPUs (for the same GPU)

This is why the ISR lock is identified as the **CRITICAL bottleneck** - it fundamentally limits the concurrency of fault processing, even though individual fault processing is highly optimized through batching.

## Fault Granularity

### Overview

Fault granularity refers to the smallest unit of memory that can trigger and be tracked as a separate fault. The UVM driver uses a multi-level granularity system:

### Hardware Fault Granularity: 4KB

**GPU Hardware Behavior**:
- GPUs report faults at **4KB (4096 bytes) granularity**
- Fault addresses from hardware are aligned to 4KB boundaries
- This is the smallest unit that can trigger a page fault

**Code Evidence**:
```c
// From uvm_gpu_replayable_faults.c:917-919
// The GPU aligns the fault addresses to 4k, but all of our tracking is
// done in PAGE_SIZE chunks which might be larger.
current_entry->fault_address = UVM_PAGE_ALIGN_DOWN(current_entry->fault_address);
```

### Software Tracking Granularity: PAGE_SIZE

**UVM Driver Behavior**:
- UVM tracks faults at **PAGE_SIZE granularity** (kernel's native page size)
- On most Linux systems: **PAGE_SIZE = 4KB**
- On ARM64 systems with 64KB pages: **PAGE_SIZE = 64KB**
- Fault addresses are aligned down to PAGE_SIZE boundaries

**Code Evidence**:
```c
// From uvm_gpu_replayable_faults.c:919
current_entry->fault_address = UVM_PAGE_ALIGN_DOWN(current_entry->fault_address);

// From uvm_gpu_non_replayable_faults.c:211
fault_entry->fault_address = UVM_PAGE_ALIGN_DOWN(fault_entry->fault_address);
```

**Implications**:
- On 4KB page systems: Hardware and software granularity match (4KB)
- On 64KB page systems: Multiple 4KB hardware faults can map to one PAGE_SIZE tracking unit
- This means UVM may service multiple 4KB faults together when they fall within the same PAGE_SIZE chunk

### VA Block Granularity: 2MB

**VA Block Structure**:
- VA blocks are **2MB (2^21 bytes)** chunks of virtual address space
- Defined by `UVM_VA_BLOCK_SIZE = (1ULL << UVM_VA_BLOCK_BITS)` where `UVM_VA_BLOCK_BITS = 21`
- Each VA block contains `PAGES_PER_UVM_VA_BLOCK = UVM_VA_BLOCK_SIZE / PAGE_SIZE` pages
- On 4KB page systems: **512 pages per VA block**
- On 64KB page systems: **32 pages per VA block**

**Code Evidence**:
```c
// From uvm_va_block_types.h:42-50
#define UVM_VA_BLOCK_BITS               21
#define UVM_VA_BLOCK_SIZE               (1ULL << UVM_VA_BLOCK_BITS)  // 2MB
#define PAGES_PER_UVM_VA_BLOCK          (UVM_VA_BLOCK_SIZE / PAGE_SIZE)
```

**Fault Tracking Within VA Blocks**:
- Faults are tracked using page masks (`uvm_page_mask_t`)
- Each bit in the mask represents one PAGE_SIZE page within the block
- Page index calculated as: `page_index = (fault_address - block_start) / PAGE_SIZE`

**Code Evidence**:
```c
// From uvm_va_block.h:1614
static uvm_page_index_t uvm_va_block_cpu_page_index(uvm_va_block_t *va_block, NvU64 addr)
{
    return (uvm_page_index_t)((addr - va_block->start) / PAGE_SIZE);
}
```

### Granularity Hierarchy Summary

```
Hardware Level:     4KB (fixed, GPU hardware)
    ↓
Software Level:     PAGE_SIZE (4KB on x86_64, 64KB on ARM64)
    ↓
VA Block Level:     2MB (UVM_VA_BLOCK_SIZE)
    ↓
VA Space Level:     Entire virtual address space
```

### Example: Fault Processing at Different Granularities

**Scenario**: GPU faults on address `0x10001234` (4KB-aligned)

1. **Hardware Reports**: Fault at `0x10001234` (4KB granularity)

2. **UVM Aligns**: 
   - On 4KB page system: `UVM_PAGE_ALIGN_DOWN(0x10001234) = 0x10001000`
   - On 64KB page system: `UVM_PAGE_ALIGN_DOWN(0x10001234) = 0x10000000`
   - Fault tracked at PAGE_SIZE boundary

3. **VA Block Lookup**:
   - Block start: `UVM_VA_BLOCK_ALIGN_DOWN(0x10001000) = 0x1000000` (2MB aligned)
   - Block contains addresses: `[0x1000000, 0x101FFFFF]` (2MB range)
   - Page index within block: `(0x10001000 - 0x1000000) / PAGE_SIZE`

4. **Fault Processing**:
   - VA block lock acquired for the 2MB block
   - Page mask bit set for the specific PAGE_SIZE page
   - All faults within the same PAGE_SIZE page are coalesced
   - Service operation applies to the PAGE_SIZE page

### Coalescing and Batching

**Fault Coalescing**:
- Multiple faults on the same PAGE_SIZE page are coalesced into one entry
- Reduces processing overhead
- Code: `uvm_gpu_replayable_faults.c:944-970` (coalescing logic)

**Batch Processing**:
- Faults are processed in batches (up to 256 faults per batch)
- Batches can contain faults from multiple VA blocks
- Within a batch, faults are grouped by VA block for efficient processing

### Performance Implications

1. **4KB vs 64KB PAGE_SIZE**:
   - 64KB pages: Fewer page table entries, but less granular fault tracking
   - 4KB pages: More granular tracking, matches hardware exactly

2. **VA Block Size (2MB)**:
   - Balances lock granularity vs. memory overhead
   - Larger blocks = fewer locks but more contention
   - Smaller blocks = more locks but better parallelism

3. **Fault Coalescing**:
   - Reduces duplicate processing
   - Important for workloads with many faults on same pages
   - Can mask some fault patterns

### Code References for Granularity

- VA block size: `uvm_va_block_types.h:42-45`
- Fault address alignment: `uvm_gpu_replayable_faults.c:917-919`
- Page index calculation: `uvm_va_block.h:1614`
- Coalescing logic: `uvm_gpu_replayable_faults.c:944-970`

## Code References

- ISR lock definitions: `kernel-open/nvidia-uvm/uvm_gpu_isr.h`, `uvm_gpu_isr.c`
- Replayable fault handler: `kernel-open/nvidia-uvm/uvm_gpu_replayable_faults.c`
- Non-replayable fault handler: `kernel-open/nvidia-uvm/uvm_gpu_non_replayable_faults.c`
- Lock ordering: `kernel-open/nvidia-uvm/uvm_lock.h`
- VA space locking: `kernel-open/nvidia-uvm/uvm_va_space.c`
- VA block locking: `kernel-open/nvidia-uvm/uvm_va_block.c`

### Key Code Locations

- ISR lock acquisition (replayable): `uvm_gpu_isr.c:742-758`
- ISR lock release (replayable): `uvm_gpu_isr.c:760-825`
- Bottom-half execution: `uvm_gpu_isr.c:598-631`
- Batch processing loop: `uvm_gpu_replayable_faults.c:2920-3013`
- Fault fetching: `uvm_gpu_replayable_faults.c:850-983`
- Batch size configuration: `uvm_gpu_replayable_faults.c:72-78`
