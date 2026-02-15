# UVM Page Size Selection Algorithm and Default Granularity

## Default Granularity

### Primary Default: PAGE_SIZE

**Default Granularity**: `PAGE_SIZE` (kernel's native page size)
- **x86_64 systems**: `PAGE_SIZE = 4KB` (4096 bytes)
- **ARM64 systems**: `PAGE_SIZE = 4KB` or `64KB` (depending on kernel configuration)

**Code Evidence**:
```c
// From uvm_va_block.c:1042
UVM_ASSERT(uvm_chunk_find_first_size(chunk_sizes) == PAGE_SIZE);
// PAGE_SIZE needs to be the lowest natively-supported chunk size
```

**UVM_PAGE_SIZE_DEFAULT**:
- When `UVM_PAGE_SIZE_DEFAULT` (value: 0) is specified, UVM uses `PAGE_SIZE`
- This is the fallback/default behavior for allocations
- Code: `uvm_mem.h:120-121` - "If set to UVM_PAGE_SIZE_DEFAULT, PAGE_SIZE size will be used"

### HMM Blocks Default

**Special Case**: HMM (Heterogeneous Memory Management) VA blocks
- **Always use**: `PAGE_SIZE` only
- No big pages supported for HMM blocks
- Code: `uvm_va_block.c:1191-1192`

```c
if (uvm_va_block_is_hmm(block))
    return PAGE_SIZE;
```

## Page Size Selection Algorithm

The UVM driver uses a **greedy largest-fit algorithm** that selects the largest possible page size based on alignment and size constraints.

### Algorithm Overview

**Selection Order** (from largest to smallest):
1. **2MB** (if perfectly aligned and sized)
2. **Big page** (128KB or 64KB, depending on architecture)
3. **PAGE_SIZE** (4KB or 64KB, fallback)

**Iteration Direction**: **Largest to smallest** (`for_each_chunk_size_rev`)

### Detailed Selection Algorithm

#### Function: `uvm_va_block_gpu_chunk_index_range()`
**Location**: `uvm_va_block.c:1020-1133`

**Input**:
- `start`: Starting address (must be PAGE_SIZE aligned)
- `size`: Size in bytes (must be PAGE_SIZE aligned)
- `page_index`: Page index within VA block
- `gpu`: GPU to select page size for

**Output**:
- `out_chunk_size`: Selected chunk size
- Returns: Number of chunks needed

**Algorithm Steps**:

```
Step 1: Initialize
  chunk_sizes = gpu->parent->mmu_user_chunk_sizes
  // Contains: PAGE_SIZE | 64KB | 128KB | 2MB (architecture-dependent)
  
Step 2: Check for perfect 2MB case (FAST PATH)
  if (chunk_sizes supports 2MB) AND 
     (size == 2MB) AND 
     (start is 2MB-aligned):
    → Return 2MB, num_chunks = 0
    → DONE
    
Step 3: Remove 2MB from consideration
  chunk_sizes &= ~UVM_CHUNK_SIZE_2M
  // Only one 2MB chunk can fit per VA block
  
Step 4: Check for perfect big page alignment (FAST PATH)
  final_chunk_size = find_largest_size(chunk_sizes)  // 128KB or 64KB
  if (start is aligned to final_chunk_size) AND 
     (size is aligned to final_chunk_size):
    → Return final_chunk_size
    → Calculate num_chunks based on alignment
    → DONE
    
Step 5: General case (SLOW PATH)
  // Iterate from largest to smallest chunk size
  for each chunk_size in chunk_sizes (largest to smallest):
    aligned_start = ALIGN_UP(start, chunk_size)
    aligned_addr  = ALIGN_DOWN(addr, chunk_size)
    aligned_end   = ALIGN_DOWN(end, chunk_size)
    
    // Check if this chunk size can cover the region
    if (aligned_start <= aligned_addr) AND
       (aligned_addr < aligned_end):
      → This chunk size works
      → Calculate how many chunks fit
      → Update running totals
      
  // Handle remaining PAGE_SIZE chunks
  num_chunks_total += (addr - start) / PAGE_SIZE
  if (no chunk size found):
    final_chunk_size = PAGE_SIZE  // Fallback
```

#### Function: `block_gpu_chunk_size()`
**Location**: `uvm_va_block.c:1183-1213`

**Purpose**: Compute the chunk size for a specific page index

**Algorithm**:

```
Step 1: HMM check
  if (block is HMM):
    return PAGE_SIZE  // HMM blocks always use PAGE_SIZE
    
Step 2: Calculate alignment constraints
  start = block->start + page_index * PAGE_SIZE
  size = block->end - start + 1
  
  // Find all sizes for which 'start' is aligned
  start_alignments = start ^ (start - 1)
  // Example: start=0x10001234 → start_alignments=0x00001111 (4KB aligned)
  
Step 3: Calculate size constraints
  // Find largest power-of-2 <= size
  pow2_leq_size = rounddown_pow_of_two(size)
  pow2_leq_size |= pow2_leq_size - 1
  // Example: size=0x20000 → pow2_leq_size=0x1FFFF (all sizes <= 128KB)
  
Step 4: Filter by GPU support and constraints
  allowed_sizes = chunk_sizes & start_alignments & pow2_leq_size
  // Intersection of:
  //   - GPU-supported sizes
  //   - Address-aligned sizes
  //   - Size-compatible sizes
  
Step 5: Select largest
  return find_largest_size(allowed_sizes)
```

#### Function: `block_calculate_largest_alloc_size()`
**Location**: `uvm_va_block.c:1594-1634`

**Purpose**: Calculate largest allocation size for CPU memory allocation

**Algorithm**:

```
Step 1: Initialize
  allocation_sizes = cpu_allocation_sizes
  // Typically: PAGE_SIZE | 64KB | 128KB | 2MB
  
Step 2: Iterate from largest to smallest
  for each alloc_size in cpu_allocation_sizes (largest to smallest):
    
    Step 2a: Calculate aligned address
      alloc_virt_addr = ALIGN_DOWN(page_address, alloc_size)
      
    Step 2b: Check VA block boundaries
      if (alloc_virt_addr < block->start) OR
         (alloc_virt_addr + alloc_size > block->end):
        → Skip this size, try next smaller
        continue
        
    Step 2c: Check for overlaps
      allocated_region = region(alloc_virt_addr, alloc_virt_addr + alloc_size)
      if (region overlaps existing allocations):
        → Skip this size, try next smaller
        continue
        
    Step 2d: Found valid size
      → Return allocation_sizes (mask with this size and smaller)
      → DONE
      
Step 3: No size found
  return UVM_CHUNK_SIZE_INVALID
```

### Selection Order Summary

**Priority Order** (highest to lowest):

1. **2MB** (`UVM_CHUNK_SIZE_2M`)
   - **Condition**: Perfect 2MB alignment AND size == 2MB
   - **Fast path**: Checked first, early return if matched

2. **128KB** (`UVM_CHUNK_SIZE_128K`) - Volta+ only
   - **Condition**: Address aligned to 128KB AND size multiple of 128KB
   - **Architecture**: Volta, Turing, Ampere, Ada, Hopper, Blackwell

3. **64KB** (`UVM_CHUNK_SIZE_64K`) - Pascal+ only
   - **Condition**: Address aligned to 64KB AND size multiple of 64KB
   - **Architecture**: Pascal, Volta, Turing, Ampere, Ada, Hopper, Blackwell

4. **PAGE_SIZE** (4KB or 64KB)
   - **Condition**: Always available, always aligned
   - **Fallback**: Used when larger sizes don't fit

### Iteration Macros

**Largest to Smallest** (`for_each_chunk_size_rev`):
```c
// From uvm_pmm_gpu.h:638-642
#define for_each_chunk_size_rev(__size, __chunk_sizes)                          \
    for ((__size) = (__chunk_sizes) ? uvm_chunk_find_last_size(__chunk_sizes) : \
                                      UVM_CHUNK_SIZE_INVALID;                   \
         (__size) != UVM_CHUNK_SIZE_INVALID;                                    \
         (__size) = uvm_chunk_find_prev_size((__chunk_sizes), (__size)))
```

**Helper Functions**:
- `uvm_chunk_find_last_size()`: Returns largest size in mask (uses `__fls()`)
- `uvm_chunk_find_prev_size()`: Returns next smaller size
- `uvm_chunk_find_first_size()`: Returns smallest size in mask (uses `__ffs()`)

### Example Selection Scenarios

#### Scenario 1: Perfect 2MB Block
```
Input:
  start = 0x2000000 (2MB aligned)
  size = 0x200000 (2MB)
  GPU: Pascal+ (supports 2MB)

Algorithm:
  Step 2: Check 2MB case
    ✓ chunk_sizes supports 2MB
    ✓ size == 2MB
    ✓ start is 2MB-aligned
  → Return: 2MB, num_chunks = 0
```

#### Scenario 2: 128KB Aligned Region (Volta+)
```
Input:
  start = 0x10020000 (128KB aligned)
  size = 0x40000 (256KB = 2 × 128KB)
  GPU: Volta (supports 128KB, 64KB, 4KB)

Algorithm:
  Step 2: 2MB check fails (size != 2MB)
  Step 4: Check big page alignment
    final_chunk_size = 128KB (largest in mask)
    ✓ start aligned to 128KB
    ✓ size aligned to 128KB
  → Return: 128KB, num_chunks = 2
```

#### Scenario 3: Misaligned Region
```
Input:
  start = 0x10001234 (4KB aligned, not 64KB aligned)
  size = 0x10000 (64KB)
  GPU: Pascal (supports 64KB, 4KB)

Algorithm:
  Step 2: 2MB check fails
  Step 4: Big page check fails (start not 64KB aligned)
  Step 5: General case
    Try 64KB: aligned_start = 0x10010000 > start → Skip
    Try 4KB: Works
  → Return: 4KB, num_chunks = 16
```

#### Scenario 4: Partial Alignment
```
Input:
  start = 0x10000000 (64KB aligned)
  size = 0x18000 (96KB = 1.5 × 64KB)
  GPU: Pascal

Algorithm:
  Step 2: 2MB check fails
  Step 4: Big page check fails (size not 64KB multiple)
  Step 5: General case
    Try 64KB: 
      - First 64KB chunk: 0x10000000-0x10010000 ✓
      - Second chunk: Would exceed size
    → Use 64KB for first chunk, 4KB for remainder
  → Return: Mixed (64KB + 4KB chunks)
```

### Architecture-Specific Supported Sizes

#### Pascal
```
mmu_user_chunk_sizes = PAGE_SIZE | 64KB | 2MB
Selection order: 2MB → 64KB → PAGE_SIZE
```

#### Volta+
```
mmu_user_chunk_sizes = PAGE_SIZE | 64KB | 128KB | 2MB
Selection order: 2MB → 128KB → 64KB → PAGE_SIZE
```

#### Maxwell
```
mmu_user_chunk_sizes = PAGE_SIZE
Selection order: PAGE_SIZE (only)
```

### Performance Optimizations

#### Fast Paths

1. **Perfect 2MB Case** (Lines 1046-1051):
   - Early return if entire 2MB block matches
   - Avoids all iteration
   - O(1) complexity

2. **Perfect Big Page Case** (Lines 1059-1063):
   - Early return if aligned to largest big page
   - Single size check
   - O(1) complexity

3. **General Case** (Lines 1086-1121):
   - Iterates largest to smallest
   - Stops when valid size found
   - O(log n) complexity where n = number of supported sizes

#### Alignment Calculation Trick

**Efficient Alignment Check**:
```c
// From uvm_va_block.c:1197
start_alignments = start ^ (start - 1);
// Creates mask of all sizes for which start is aligned
// Example: start=0x10001234 → 0x00001111 (aligned to 4KB, 8KB, 16KB, 32KB)
```

This single operation determines all valid alignment sizes without multiple checks.

### Code Flow Diagram

```
uvm_va_block_gpu_chunk_index_range()
  │
  ├─> [Fast Path 1] Check 2MB perfect case
  │   └─> if (2MB aligned && size == 2MB) → Return 2MB
  │
  ├─> Remove 2MB from mask
  │
  ├─> [Fast Path 2] Check big page perfect case
  │   └─> if (aligned to largest big page) → Return big page
  │
  └─> [General Path] Iterate largest to smallest
      │
      ├─> for each chunk_size (largest → smallest):
      │   ├─> Calculate aligned boundaries
      │   ├─> Check if fits
      │   └─> if fits → Use this size
      │
      └─> Fallback: Use PAGE_SIZE
```

### Key Constraints

1. **Minimum Size**: Always `PAGE_SIZE` (cannot be smaller)
2. **Maximum Size**: `UVM_CHUNK_SIZE_MAX` (2MB)
3. **Alignment**: Must match chunk size boundary
4. **Size**: Must be multiple of chunk size
5. **VA Block**: Cannot exceed VA block boundaries (2MB)

### Default Behavior Summary

| Context | Default Granularity | Notes |
|---------|---------------------|-------|
| **General allocations** | `PAGE_SIZE` | 4KB (x86_64) or 64KB (ARM64) |
| **HMM blocks** | `PAGE_SIZE` | Always, no big pages |
| **GPU mappings** | Largest supported | Up to 2MB if aligned |
| **CPU allocations** | Largest available | Up to 2MB if aligned |
| **UVM_PAGE_SIZE_DEFAULT** | `PAGE_SIZE` | Value 0 means use PAGE_SIZE |

### Selection Algorithm Pseudocode

```python
def select_chunk_size(start, size, gpu):
    chunk_sizes = gpu.mmu_user_chunk_sizes  # Mask of supported sizes
    
    # Fast path 1: Perfect 2MB case
    if (chunk_sizes & 2MB) and (size == 2MB) and is_aligned(start, 2MB):
        return 2MB
    
    # Remove 2MB from consideration
    chunk_sizes &= ~2MB
    
    # Fast path 2: Perfect big page case
    largest_big = find_largest_size(chunk_sizes)  # 128KB or 64KB
    if is_aligned(start, largest_big) and is_aligned(size, largest_big):
        return largest_big
    
    # General case: Iterate largest to smallest
    for chunk_size in iterate_largest_to_smallest(chunk_sizes):
        aligned_start = align_up(start, chunk_size)
        aligned_addr = align_down(start, chunk_size)
        aligned_end = align_down(start + size, chunk_size)
        
        if aligned_start <= aligned_addr < aligned_end:
            # This size works
            return chunk_size
    
    # Fallback: Always works
    return PAGE_SIZE
```

## Code References

### Key Functions

- **Main selection**: `uvm_va_block.c:1020-1133` (`uvm_va_block_gpu_chunk_index_range`)
- **Chunk size calculation**: `uvm_va_block.c:1183-1213` (`block_gpu_chunk_size`)
- **Allocation size**: `uvm_va_block.c:1594-1634` (`block_calculate_largest_alloc_size`)
- **Helper macros**: `uvm_pmm_gpu.h:631-654` (`for_each_chunk_size_rev`)
- **Size finders**: `uvm_pmm_gpu.h:580-613` (`uvm_chunk_find_*_size`)

### Key Constants

- **Default**: `PAGE_SIZE` (kernel-defined, typically 4KB)
- **UVM_PAGE_SIZE_DEFAULT**: `0` (means use PAGE_SIZE)
- **Minimum**: `PAGE_SIZE` (always supported)
- **Maximum**: `UVM_CHUNK_SIZE_MAX` = 2MB

## Summary

**Default Granularity**: `PAGE_SIZE` (4KB on x86_64, 64KB on ARM64)

**Selection Algorithm**: Greedy largest-fit, iterating from largest to smallest:
1. Check 2MB (perfect case)
2. Check largest big page (128KB or 64KB, perfect case)
3. Iterate largest to smallest (general case)
4. Fallback to PAGE_SIZE

**Key Principle**: Always prefer the largest page size that fits alignment and size constraints, maximizing TLB efficiency and minimizing page table overhead.
