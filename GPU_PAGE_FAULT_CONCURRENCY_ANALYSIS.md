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

- **Replayable faults**: Single exclusive lock per GPU (`parent_gpu->isr.replayable_faults.service_lock`)
  - Only ONE bottom-half can process replayable faults at a time per GPU
  - Lock is held for the entire fault processing batch
  - Batch size is configurable (default: 256 faults, max: 20 batches per service)
  
- **Non-replayable faults**: Single exclusive lock per GPU (`parent_gpu->isr.non_replayable_faults.service_lock`)
  - Multiple bottom-halves can be scheduled but serialize on this lock
  - Lock is held for processing all pending faults
  
**Why it's a bottleneck**:
- Serializes ALL fault processing for a GPU
- Cannot parallelize fault handling across multiple CPUs/threads for the same GPU
- Long critical section: includes fault fetching, parsing, VA space lookups, block servicing, and GPU work submission

**Mitigation attempts**:
- Batching reduces lock acquisition overhead
- VA block-level locking allows some parallelism within a batch
- But the ISR lock still serializes the entire batch processing

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

## Concurrency Characteristics

### Parallelism Opportunities

1. **Different GPUs**: Fault handlers for different GPUs can run in parallel (separate ISR locks)
2. **Different VA Spaces**: Faults from different VA spaces can be processed concurrently (separate VA space locks)
3. **Different VA Blocks**: Faults on different VA blocks can be serviced concurrently (separate VA block locks)

### Serialization Points

1. **Same GPU, Replayable Faults**: Serialized by ISR service lock
2. **Same GPU, Non-Replayable Faults**: Serialized by ISR service lock
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

## Code References

- ISR lock definitions: `kernel-open/nvidia-uvm/uvm_gpu_isr.h`, `uvm_gpu_isr.c`
- Replayable fault handler: `kernel-open/nvidia-uvm/uvm_gpu_replayable_faults.c`
- Non-replayable fault handler: `kernel-open/nvidia-uvm/uvm_gpu_non_replayable_faults.c`
- Lock ordering: `kernel-open/nvidia-uvm/uvm_lock.h`
- VA space locking: `kernel-open/nvidia-uvm/uvm_va_space.c`
- VA block locking: `kernel-open/nvidia-uvm/uvm_va_block.c`
