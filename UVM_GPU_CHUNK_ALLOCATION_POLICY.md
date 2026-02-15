# GPU Chunk Allocation Policy and Algorithm During Page Faults

## Overview

When a GPU page fault occurs, the UVM driver must allocate GPU memory chunks to back the faulting pages. This document analyzes the policy and algorithm used for GPU chunk allocation during fault handling.

## Allocation Policy

### Core Policy: Largest-Fit Chunk Size Selection

**Policy**: Allocate the largest possible GPU chunk size that:
- Is supported by the GPU architecture
- Matches the address alignment constraints
- Fits within the VA block boundaries
- Minimizes the number of allocations needed

**Rationale**:
- **Fewer allocations**: Larger chunks reduce allocation overhead
- **Better memory locality**: Contiguous chunks improve cache performance
- **Reduced fragmentation**: Fewer allocations mean less fragmentation
- **Lower overhead**: Fewer chunk management operations

### Default Granularity

**Default Chunk Size**: Determined dynamically based on:
- **Address alignment**: Must be aligned to chunk size boundary
- **Remaining size**: Must fit within VA block
- **GPU support**: Must be supported by GPU architecture

**No Fixed Default**: Unlike CPU allocations which default to PAGE_SIZE, GPU chunk sizes are always selected based on alignment and size constraints.

## Allocation Algorithm

### High-Level Flow

```
GPU Page Fault Occurs
  ↓
uvm_va_block_service_locked()
  ↓
uvm_va_block_service_copy()
  ↓
uvm_va_block_make_resident_copy()
  ↓
block_populate_pages()
  ↓
uvm_va_block_populate_pages_gpu()
  ↓
block_populate_gpu_chunk()
  ↓
block_alloc_gpu_chunk()
  ↓
uvm_pmm_gpu_alloc_user()
```

### Detailed Algorithm

#### Step 1: Determine Chunk Size for Each Page

**Function**: `block_gpu_chunk_size()` (`uvm_va_block.c:1183-1213`)

**Algorithm**:
```c
1. Calculate start address and remaining size
   start = block->start + page_index * PAGE_SIZE
   size = block->end - start + 1

2. Calculate alignment constraints
   start_alignments = start ^ (start - 1)
   // Creates mask of all sizes for which start is aligned
   // Example: start=0x10001234 → aligned to 4KB, 8KB, 16KB, 32KB

3. Calculate size constraints
   pow2_leq_size = rounddown_pow_of_two(size)
   pow2_leq_size |= pow2_leq_size - 1
   // Creates mask of all sizes <= size

4. Filter by GPU support and constraints
   allowed_sizes = chunk_sizes & start_alignments & pow2_leq_size
   // Intersection of:
   //   - GPU-supported sizes (from mmu_user_chunk_sizes)
   //   - Address-aligned sizes
   //   - Size-compatible sizes

5. Select largest
   return find_largest_size(allowed_sizes)
```

**Key Points**:
- Uses same algorithm as page size selection for mappings
- Considers alignment, size, and GPU capabilities
- Always selects largest possible size

#### Step 2: Iterate Over Faulting Pages

**Function**: `uvm_va_block_populate_pages_gpu()` (`uvm_va_block.c:2996-3035`)

**Algorithm**:
```c
1. Find first faulting page in region
   page_index = first_page_in_mask(region, populate_mask)

2. Calculate chunk index and size for this page
   chunk_index = block_gpu_chunk_index(block, gpu, page_index, &chunk_size)
   chunk_region = chunk_region_for_size(chunk_size, page_index)

3. Loop over all chunks needed:
   while (chunk_region.outer < region.outer):
       if (chunk overlaps populate_mask):
           block_populate_gpu_chunk()  // Allocate chunk
       
       // Move to next chunk
       chunk_index++
       chunk_size = block_gpu_chunk_size(block, gpu, chunk_region.outer)
       chunk_region = next_chunk_region(chunk_size)
```

**Chunk Size Selection Order**:
- Determined per-page based on alignment
- Can vary within a single VA block
- Always selects largest possible size for each chunk

#### Step 3: Allocate GPU Chunk

**Function**: `block_alloc_gpu_chunk()` (`uvm_va_block.c:1978-2023`)

**Allocation Policy**:

```
Step 1: Check retry free chunks
  gpu_chunk = block_retry_get_free_chunk(retry, gpu, size)
  if (found):
    → Return immediately (reuse from previous allocation attempt)

Step 2: Try allocation without eviction
  status = uvm_pmm_gpu_alloc_user(pmm, 1, size, 
                                   UVM_PMM_ALLOC_FLAGS_NONE, 
                                   &gpu_chunk, tracker)
  if (success):
    → Return chunk

Step 3: If no memory, try with eviction
  if (status == NV_ERR_NO_MEMORY):
    → Unlock VA block lock (eviction may need it)
    → status = uvm_pmm_gpu_alloc_user(pmm, 1, size,
                                       UVM_PMM_ALLOC_FLAGS_EVICT,
                                       &gpu_chunk, tracker)
    → Add to retry free chunks list
    → Return NV_ERR_MORE_PROCESSING_REQUIRED (forces retry)
    → Relock VA block lock
```

**Key Policy Points**:

1. **Two-Stage Allocation**:
   - **First attempt**: No eviction (`UVM_PMM_ALLOC_FLAGS_NONE`)
   - **Second attempt**: With eviction (`UVM_PMM_ALLOC_FLAGS_EVICT`)

2. **Eviction Handling**:
   - VA block lock is **unlocked** before eviction
   - This allows eviction to proceed without deadlocks
   - Operation must be retried after eviction completes

3. **Chunk Reuse**:
   - Previously allocated chunks stored in `retry->used_chunks`
   - Checked before new allocation
   - Reduces redundant allocations during retries

#### Step 4: Populate and Initialize Chunk

**Function**: `block_populate_gpu_chunk()` (`uvm_va_block.c:2899-2993`)

**Algorithm**:

```
Step 1: Check if chunk already exists
  if (gpu_state->chunks[chunk_index] != NULL):
    → Check if zeroing needed
    → Return NV_OK (reuse existing)

Step 2: Allocate chunk
  status = block_alloc_gpu_chunk(block, retry, gpu, chunk_size, &chunk)

Step 3: Map chunk (for SR-IOV)
  status = uvm_mmu_chunk_map(chunk)
  // Creates virtual mapping if needed

Step 4: Zero chunk
  status = block_zero_new_gpu_chunk(block, gpu, chunk, chunk_region, tracker)
  // Ensures security: uninitialized memory is zeroed

Step 5: Initialize chunk metadata
  chunk->va_block_page_index = chunk_region.first
  chunk->va_block = block
  gpu_state->chunks[chunk_index] = chunk

Step 6: Add to retry list
  block_retry_add_used_chunk(retry, chunk)
  // Tracks chunk for cleanup on failure
```

**Zeroing Policy**:
- **Always zero new chunks**: Security requirement
- **Skip zeroing if**:
  - Chunk was zeroed by RM and never modified (`chunk->is_zero`)
  - Block was ever fully resident on GPU (`ever_fully_resident`)
  - No discarded pages in chunk region

## Chunk Size Selection During Faults

### Selection Order

**Same as Page Size Selection** (from largest to smallest):

1. **2MB** (`UVM_CHUNK_SIZE_2M`)
   - If entire VA block is 2MB-aligned and sized
   - Perfect case: single chunk per VA block

2. **128KB** (`UVM_CHUNK_SIZE_128K`) - Volta+
   - If address aligned to 128KB
   - If size >= 128KB

3. **64KB** (`UVM_CHUNK_SIZE_64K`) - Pascal+
   - If address aligned to 64KB
   - If size >= 64KB

4. **PAGE_SIZE** (4KB or 64KB)
   - Fallback: always works
   - Used when larger sizes don't align

### Example Scenarios

#### Scenario 1: Perfect 2MB Alignment
```
Fault Address: 0x2000000 (2MB aligned)
VA Block: [0x2000000, 0x201FFFFF] (2MB)
GPU: Pascal+ (supports 2MB)

Selection:
  → chunk_size = 2MB (perfect alignment)
  → Single chunk allocation
  → Optimal: 1 allocation for entire block
```

#### Scenario 2: 128KB Alignment (Volta+)
```
Fault Address: 0x10020000 (128KB aligned)
VA Block: [0x10020000, 0x1003FFFF] (128KB)
GPU: Volta (supports 128KB, 64KB, 4KB)

Selection:
  → chunk_size = 128KB (aligned and fits)
  → Single chunk allocation
  → Good: 1 allocation for 128KB
```

#### Scenario 3: Misaligned Address
```
Fault Address: 0x10001234 (4KB aligned, not 64KB aligned)
VA Block: [0x10000000, 0x1001FFFF] (128KB)
GPU: Pascal (supports 64KB, 4KB)

Selection:
  → First chunk: 4KB (misaligned start)
  → Remaining chunks: 64KB (aligned)
  → Result: Mixed chunk sizes
  → Suboptimal: Multiple allocations needed
```

#### Scenario 4: Partial Block Fault
```
Fault Address: 0x10001000 (4KB aligned)
VA Block: [0x10000000, 0x1001FFFF] (128KB)
Faulting Pages: [0x10001000, 0x10001FFF] (4KB)
GPU: Pascal

Selection:
  → chunk_size = 4KB (only 4KB needed)
  → Single 4KB chunk allocation
  → Efficient: Only allocates what's needed
```

## Allocation Flags and Policies

### Allocation Flags

**UVM_PMM_ALLOC_FLAGS_NONE** (Default):
- **Policy**: Try allocation without eviction
- **Behavior**: Returns `NV_ERR_NO_MEMORY` if no free memory
- **Use case**: First allocation attempt

**UVM_PMM_ALLOC_FLAGS_EVICT**:
- **Policy**: Allow eviction if no free memory
- **Behavior**: May evict other user chunks to satisfy allocation
- **Use case**: Second attempt after `NV_ERR_NO_MEMORY`
- **Locking**: VA block lock must be unlocked (eviction needs it)

**UVM_PMM_ALLOC_FLAGS_DONT_BATCH**:
- **Policy**: Disable batching for PMA page allocation
- **Behavior**: Allocate pages individually
- **Use case**: Special cases requiring immediate allocation

### Eviction Policy

**When Eviction Occurs**:
- First allocation attempt fails with `NV_ERR_NO_MEMORY`
- Second attempt uses `UVM_PMM_ALLOC_FLAGS_EVICT`
- PMM selects chunks to evict based on eviction policies

**Eviction Process**:
1. Unlock VA block lock (prevents deadlock)
2. PMM selects victim chunks (LRU, access patterns, etc.)
3. Evict victim chunks (unmap, migrate to CPU if needed)
4. Allocate new chunk from freed memory
5. Return `NV_ERR_MORE_PROCESSING_REQUIRED`
6. Relock VA block lock
7. Retry operation

**Eviction Scope**:
- Only **user memory** chunks can be evicted
- Kernel memory chunks cannot be evicted
- Eviction is transparent to fault handling

## Chunk Size Constraints

### Minimum Size

**Always**: `PAGE_SIZE` (4KB or 64KB)
- UVM never allocates chunks smaller than PAGE_SIZE
- This matches the minimum page size for mappings

### Maximum Size

**Always**: `UVM_CHUNK_SIZE_MAX` = 2MB
- Limited by VA block size (2MB)
- Cannot allocate larger chunks than VA block

### Alignment Requirements

**Strict Alignment**:
- Chunk address must be aligned to chunk size
- Example: 64KB chunk must start at 64KB boundary
- Enforced by `block_gpu_chunk_size()` algorithm

**Size Requirements**:
- Chunk size must divide remaining size evenly
- Cannot allocate chunk larger than remaining space

## Performance Optimizations

### 1. Chunk Reuse

**Policy**: Reuse chunks from previous allocation attempts

**Implementation**:
- Chunks stored in `retry->used_chunks` list
- Checked before new allocation
- Reduces redundant allocations during retries

**Code**: `uvm_va_block.c:1988` (`block_retry_get_free_chunk`)

### 2. Largest-Fit Selection

**Policy**: Always prefer larger chunks

**Benefits**:
- Fewer allocations per VA block
- Better memory locality
- Reduced fragmentation
- Lower allocation overhead

**Trade-off**:
- May allocate more memory than strictly needed
- But improves overall performance

### 3. Zeroing Optimization

**Policy**: Skip zeroing when safe

**Skip Conditions**:
- Chunk was zeroed by RM (`chunk->is_zero`)
- Block was ever fully resident (`ever_fully_resident`)
- No discarded pages in chunk region

**Security**: Always zero when in doubt

**Code**: `uvm_va_block.c:2927-2930`

### 4. Virtual Mapping Optimization

**Policy**: Only create virtual mappings when needed

**When Needed**:
- SR-IOV heavy mode (cannot use physical addresses)
- Confidential Computing configurations

**Code**: `uvm_va_block.c:2944` (`uvm_mmu_chunk_map`)

## Interaction with Residency Selection

### Residency Selection First

**Order**: Residency selection happens **before** chunk allocation

**Process**:
```
1. uvm_va_block_select_residency()
   → Determines destination processor (CPU or GPU)
   → Considers: preferred_location, accessed_by, thrashing hints

2. If destination is GPU:
   → block_populate_pages()
   → uvm_va_block_populate_pages_gpu()
   → Chunk allocation happens here

3. If destination is CPU:
   → block_populate_pages_cpu()
   → CPU chunk allocation (different policy)
```

### Chunk Size Based on Destination

**GPU Destination**:
- Chunk size selected based on GPU alignment constraints
- Uses `mmu_user_chunk_sizes` mask
- Can use big pages (64KB, 128KB, 2MB)

**CPU Destination**:
- Chunk size selected based on CPU allocation sizes
- Uses `uvm_cpu_chunk_get_allocation_sizes()`
- Typically: PAGE_SIZE, 64KB, 128KB, 2MB

## Memory Type Policy

### User Memory (`UVM_PMM_GPU_MEMORY_TYPE_USER`)

**Characteristics**:
- Used for backing user pages
- **Can be evicted** (Pascal+)
- Supports oversubscription
- Used during fault handling

**Allocation Function**: `uvm_pmm_gpu_alloc_user()`

### Kernel Memory (`UVM_PMM_GPU_MEMORY_TYPE_KERNEL`)

**Characteristics**:
- Used for internal UVM allocations
- **Cannot be evicted**
- Not used during fault handling
- Reserved for driver infrastructure

## Allocation Retry Mechanism

### Retry Structure

**Purpose**: Handle eviction and allocation failures gracefully

**Components**:
- `retry->used_chunks`: List of allocated chunks
- `retry->free_chunks`: List of free chunks from previous attempts
- `retry->tracker`: Tracks GPU operations

### Retry Flow

```
First Attempt:
  → Try allocation without eviction
  → If fails: unlock lock, try with eviction
  → Return NV_ERR_MORE_PROCESSING_REQUIRED

Retry:
  → Relock VA block lock
  → Check free_chunks (may have chunks from eviction)
  → Retry allocation
  → Continue operation
```

**Code**: `uvm_va_block.c:2001-2014`

## Error Handling

### Allocation Failures

**NV_ERR_NO_MEMORY**:
- No free memory available
- Triggers eviction attempt
- If eviction fails: fatal error

**NV_ERR_MORE_PROCESSING_REQUIRED**:
- Eviction occurred, operation must retry
- Chunks added to free_chunks list
- VA block lock was unlocked/relocked

**Other Errors**:
- Fatal: operation fails
- Chunks cleaned up via retry mechanism

### Cleanup on Failure

**Policy**: Clean up allocated chunks on failure

**Process**:
- Chunks tracked in `retry->used_chunks`
- On failure: unpin and free chunks
- Prevents memory leaks

**Code**: `uvm_va_block.c:4852-4876` (`block_cleanup_temp_pinned_gpu_chunks`)

## Code Flow Diagram

```
GPU Page Fault
  ↓
uvm_va_block_service_locked()
  ↓
uvm_va_block_select_residency()
  → Determines: destination = GPU
  ↓
uvm_va_block_service_copy()
  ↓
uvm_va_block_make_resident_copy()
  ↓
block_populate_pages()
  ↓
uvm_va_block_populate_pages_gpu()
  │
  ├─> For each faulting page:
  │   │
  │   ├─> block_gpu_chunk_index()
  │   │   → Calculate chunk_index and chunk_size
  │   │   → Uses: block_gpu_chunk_size()
  │   │   → Selects largest possible size
  │   │
  │   └─> block_populate_gpu_chunk()
  │       │
  │       ├─> Check if chunk exists
  │       │   → If yes: return (reuse)
  │       │
  │       ├─> block_alloc_gpu_chunk()
  │       │   │
  │       │   ├─> Check retry free_chunks
  │       │   │   → If found: reuse
  │       │   │
  │       │   ├─> Try: UVM_PMM_ALLOC_FLAGS_NONE
  │       │   │   → If success: done
  │       │   │   → If NV_ERR_NO_MEMORY: continue
  │       │   │
  │       │   └─> Try: UVM_PMM_ALLOC_FLAGS_EVICT
  │       │       → Unlock VA block lock
  │       │       → Allocate with eviction
  │       │       → Return NV_ERR_MORE_PROCESSING_REQUIRED
  │       │
  │       ├─> uvm_mmu_chunk_map()
  │       │   → Create virtual mapping (if needed)
  │       │
  │       ├─> block_zero_new_gpu_chunk()
  │       │   → Zero chunk (security)
  │       │
  │       └─> Store chunk in gpu_state->chunks[chunk_index]
  │
  └─> Continue with copy operations
```

## Summary

### Key Policies

1. **Largest-Fit Selection**: Always prefer largest possible chunk size
2. **Two-Stage Allocation**: Try without eviction first, then with eviction
3. **Chunk Reuse**: Reuse chunks from previous attempts when possible
4. **Security**: Always zero new chunks (unless proven safe)
5. **Eviction Support**: Allow eviction when memory is tight

### Algorithm Characteristics

- **Greedy**: Always selects largest size that fits
- **Adaptive**: Chunk size varies based on alignment
- **Efficient**: Minimizes number of allocations
- **Robust**: Handles eviction and retries gracefully

### Performance Impact

- **Optimal case**: Single 2MB chunk for entire VA block
- **Good case**: Few large chunks (64KB/128KB)
- **Suboptimal case**: Many small chunks (4KB) due to misalignment
- **Eviction overhead**: Additional latency when memory is tight

## Code References

### Key Functions

- **Chunk size selection**: `uvm_va_block.c:1183-1213` (`block_gpu_chunk_size`)
- **Chunk index calculation**: `uvm_va_block.c:1020-1133` (`uvm_va_block_gpu_chunk_index_range`)
- **GPU population**: `uvm_va_block.c:2996-3035` (`uvm_va_block_populate_pages_gpu`)
- **Chunk allocation**: `uvm_va_block.c:1978-2023` (`block_alloc_gpu_chunk`)
- **Chunk population**: `uvm_va_block.c:2899-2993` (`block_populate_gpu_chunk`)
- **PMM allocation**: `uvm_pmm_gpu.h:469` (`uvm_pmm_gpu_alloc_user`)

### Key Data Structures

- **Chunk sizes mask**: `gpu->parent->mmu_user_chunk_sizes`
- **Retry structure**: `uvm_va_block_retry_t` (tracks chunks)
- **GPU state**: `uvm_va_block_gpu_state_t` (stores chunks array)
- **Allocation flags**: `uvm_pmm_alloc_flags_t` (NONE, EVICT, DONT_BATCH)
