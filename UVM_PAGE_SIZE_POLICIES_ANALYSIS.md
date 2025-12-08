# UVM Driver Page Size Policies Analysis

## Overview

The NVIDIA UVM driver implements a sophisticated multi-level page size policy system that balances memory efficiency, performance, and hardware compatibility. This document analyzes how page sizes are selected, managed, and optimized.

## Supported Page Sizes

### GPU Page Sizes

The UVM driver supports multiple GPU page sizes, depending on GPU architecture:

1. **4KB** (`UVM_PAGE_SIZE_4K`): Base page size, always supported
2. **64KB** (`UVM_PAGE_SIZE_64K`): Big page size (Pascal+)
3. **128KB** (`UVM_PAGE_SIZE_128K`): Big page size (Volta+)
4. **2MB** (`UVM_PAGE_SIZE_2M`): Largest page size (Pascal+)

### Architecture Support

- **Maxwell**: 4KB only
- **Pascal**: 4KB, 64KB, 2MB
- **Volta+**: 4KB, 64KB, 128KB, 2MB
- **Turing+**: 4KB, 64KB, 128KB, 2MB (with HMM support)

### CPU Page Sizes

- **x86_64**: Typically 4KB (`PAGE_SIZE = 4096`)
- **ARM64**: Can be 4KB or 64KB (`PAGE_SIZE = 4096` or `65536`)

## Page Size Selection Policies

### 1. Initial Page Size Selection

**Policy**: Use the largest page size that:
- Is supported by the GPU architecture
- Fits within the VA block alignment constraints
- Matches the allocation size and alignment

**Code Location**: `uvm_va_block.c:1020-1120` (`uvm_va_block_gpu_chunk_index_range`)

**Selection Algorithm**:
```c
// Priority order:
1. If entire 2MB block is aligned and sized → Use 2MB
2. If aligned to largest supported big page → Use that size
3. Otherwise → Use PAGE_SIZE (4KB or 64KB)
```

**Key Factors**:
- **Address alignment**: Must be aligned to page size boundary
- **Size alignment**: Must be multiple of page size
- **VA block constraints**: VA blocks are 2MB, so 2MB pages only work for perfectly aligned blocks

### 2. Big Page Size Configuration

**Per-GPU-VA-Space Configuration**:
- Each GPU VA space has a `big_page_size` (64KB or 128KB)
- Set during GPU VA space initialization
- Determines the default big page size for mappings

**Code Location**: `uvm_mmu.c:1119-1139` (`uvm_mmu_init_gpu_va_space`)

**Policy**:
- **Volta+**: Uses 128KB if supported, otherwise 64KB
- **Pascal**: Uses 64KB
- **Maxwell**: No big pages

### 3. Chunk Size Masks

**User Chunk Sizes** (`mmu_user_chunk_sizes`):
- Determines which page sizes can be used for user allocations
- Includes: PAGE_SIZE, 64KB (if supported), 128KB (if supported), 2MB (if supported)
- Always includes PAGE_SIZE as minimum

**Kernel Chunk Sizes** (`mmu_kernel_chunk_sizes`):
- Used for kernel-space mappings
- Typically includes 64KB and 128KB (if supported)
- Does not include 2MB (reserved for user space)

**Code Location**: `uvm_mmu.c:2429-2448` (`uvm_mmu_init_gpu_chunk_sizes`)

## Page Size Selection During Mapping

### 1. Initial Mapping Policy

**Policy**: Prefer largest possible page size

**Selection Process**:
1. Check if 2MB page can be used (block-aligned, 2MB size)
2. Check if big page (64KB/128KB) can be used (aligned to big page size)
3. Fall back to PAGE_SIZE (4KB/64KB)

**Code Location**: `uvm_va_block.c:1020-1120`

**Example**:
```c
// Perfect 2MB block
if (size == UVM_CHUNK_SIZE_2M && IS_ALIGNED(start, UVM_CHUNK_SIZE_2M))
    → Use 2MB page

// Big page aligned region
if (IS_ALIGNED(start, big_page_size) && IS_ALIGNED(size, big_page_size))
    → Use big page (64KB or 128KB)

// Otherwise
    → Use PAGE_SIZE
```

### 2. Dynamic Page Size Selection

**During Fault Servicing**:
- Page size selection happens when mapping pages during fault handling
- Considers:
  - Current residency location (CPU vs GPU)
  - Allocation sizes available
  - Alignment constraints
  - Policy preferences

**Code Location**: `uvm_va_block.c:1594-1601` (`block_calculate_largest_alloc_size`)

**Factors Considered**:
- **CPU allocation sizes**: What chunk sizes are available from CPU allocator
- **GPU allocation sizes**: What chunk sizes GPU PMM can provide
- **Alignment**: Address and size alignment requirements
- **Policy**: Preferred location, accessed_by processors

### 3. Page Size Constraints

**Minimum Size**: Always PAGE_SIZE (4KB or 64KB)
- UVM never allocates chunks smaller than PAGE_SIZE
- PTEs can map smaller regions, but allocations are PAGE_SIZE minimum

**Maximum Size**: 2MB (`UVM_CHUNK_SIZE_MAX`)
- Limited by VA block size (2MB)
- Cannot use larger pages than VA block size

**Alignment Requirements**:
- Page size must align with address
- Page size must divide size evenly
- Big pages require stricter alignment

## Page Size Splitting and Merging Policies

### 1. PTE Splitting

**When Splitting Occurs**:
- **Permission changes**: Different permissions on sub-regions require 4KB PTEs
- **Partial mappings**: Only part of a big page needs mapping
- **Fault granularity**: Faults on specific 4KB pages within a big page
- **Migration**: Moving part of a big page to different location

**Code Location**: `uvm_va_block.c:6222-6238` (`block_gpu_pte_big_split_write_4k`)

**Splitting Process**:
1. Allocate 4KB page table entries
2. Copy permissions from big PTE to 4KB PTEs
3. Update mappings for sub-regions
4. Invalidate TLB entries

**Example**:
```
Big Page (64KB) with READ permission
    ↓ [Split needed for write access to middle 4KB]
4KB READ | 4KB WRITE | 4KB READ | ... (remaining 4KB pages)
```

### 2. PTE Merging

**When Merging Occurs**:
- **Uniform permissions**: All 4KB PTEs have same permissions
- **Contiguous mappings**: All 4KB pages map to contiguous physical memory
- **Performance optimization**: Reduce page table overhead

**Code Location**: `uvm_va_block.c:6445-6507` (`block_gpu_pte_merge_big_and_end`)

**Merging Process**:
1. Check if all 4KB PTEs have same permissions
2. Verify contiguous physical addresses
3. Create big PTE covering entire region
4. Remove 4KB PTEs
5. Invalidate TLB entries

**Merging Conditions**:
- All PTEs must have identical permissions
- Physical addresses must be contiguous
- Alignment must match big page size
- No partial mappings in the region

### 3. 2MB PTE Handling

**Special Case**: 2MB PTEs (PDEs)
- 2MB pages are represented as PDEs (Page Directory Entries), not PTEs
- Can be split to big pages (64KB/128KB) or 4KB PTEs
- Merging requires all sub-entries to be uniform

**Code Location**: `uvm_va_block.c:6636-6681` (`block_gpu_pte_finish_split_2m`, `block_gpu_pte_merge_2m`)

**2MB Split Process**:
```
2MB PDE
    ↓ [Split to 4KB PTEs for granular control]
32 × 64KB big pages OR 512 × 4KB PTEs
```

## Architecture-Specific Policies

### Pascal Architecture

**Supported Sizes**: 4KB, 64KB, 2MB
- **Big page size**: 64KB
- **2MB support**: Yes (for perfectly aligned blocks)
- **128KB**: Not supported

**Policy**: Prefer 64KB big pages when possible

### Volta Architecture

**Supported Sizes**: 4KB, 64KB, 128KB, 2MB
- **Big page size**: 128KB (preferred), 64KB (fallback)
- **2MB support**: Yes
- **Policy**: Prefer 128KB over 64KB

**Code Location**: `uvm_volta_mmu.c:255-267`

### Turing+ Architecture

**Supported Sizes**: 4KB, 64KB, 128KB, 2MB
- **Big page size**: 128KB (preferred)
- **HMM support**: Yes (big pages supported)
- **Policy**: Same as Volta

## Performance Optimization Policies

### 1. Big Page Preference

**Policy**: Always prefer larger page sizes when possible

**Benefits**:
- **Fewer TLB misses**: Larger pages reduce TLB pressure
- **Fewer page table entries**: Reduces memory overhead
- **Better cache locality**: Larger contiguous mappings
- **Reduced page table walk overhead**: Fewer levels to traverse

**Trade-offs**:
- **Less granular control**: Cannot set different permissions per 4KB
- **Higher memory waste**: Unused portions of big pages waste memory
- **More expensive splits**: Splitting big pages is costly

### 2. Alignment Optimization

**Policy**: Encourage 2MB-aligned allocations

**Benefits**:
- Enables 2MB page usage
- Reduces page table overhead
- Improves TLB efficiency

**Implementation**:
- VA blocks are 2MB-aligned
- User allocations aligned to 2MB can use 2MB pages
- Code comments recommend 2MB-aligned allocations for best performance

**Code Location**: `uvm_va_block.h:71-72`

### 3. Dynamic Splitting/Merging

**Policy**: Split only when necessary, merge when possible

**Splitting Triggers**:
- Permission changes on sub-regions
- Partial migrations
- Fault granularity requirements

**Merging Opportunities**:
- After migrations complete
- When permissions become uniform
- During cleanup operations

**Performance Impact**:
- Splitting: Expensive (allocates page tables, updates mappings)
- Merging: Moderate cost (consolidates entries, reduces overhead)

## Policy Interaction with Other Systems

### 1. Migration Policies

**Page Size During Migration**:
- Source and destination can use different page sizes
- Migration may require splitting if destination doesn't support big pages
- Prefers maintaining page size when possible

**Code Location**: `uvm_va_block.c:11807` (`uvm_va_block_select_residency`)

### 2. Access Counter Policies

**Page Size Impact**:
- Access counters work with all page sizes
- Big pages reduce counter overhead (fewer entries to track)
- 4KB pages provide finer-grained access tracking

### 3. Prefetch Policies

**Page Size Selection**:
- Prefetch heuristics consider page sizes
- Prefers prefetching aligned to big page boundaries
- Can trigger migrations to enable big page usage

**Code Location**: `uvm_perf_prefetch.c:268`

### 4. Thrashing Detection

**Page Size Impact**:
- Big pages can mask thrashing (all pages in big page migrate together)
- 4KB pages provide better thrashing detection granularity
- Policy may split big pages to detect thrashing

## Memory Allocation Policies

### 1. CPU Chunk Allocation

**Supported Sizes**: PAGE_SIZE, 64KB, 128KB, 2MB

**Selection Policy**:
- Prefer largest available size
- Must align with address and size
- Considers allocation size mask constraints

**Code Location**: `uvm_pmm_sysmem.h:39`

### 2. GPU Chunk Allocation

**Supported Sizes**: Depends on GPU architecture

**Selection Policy**:
- Uses GPU PMM (Physical Memory Manager)
- Prefers larger chunks when available
- Considers eviction policies

**Code Location**: `uvm_pmm_gpu.h`

## Configuration and Tuning

### 1. Module Parameters

**None Currently**: Page size policies are not user-configurable via module parameters

**Future Considerations**:
- Could add parameters to disable big pages
- Could add parameters to prefer certain page sizes
- Could add parameters to control splitting/merging aggressiveness

### 2. API-Level Control

**Limited Control**: 
- User can set preferred location (affects migration, indirectly affects page sizes)
- User cannot directly control page size selection
- Page size is determined automatically by UVM

### 3. Test Interface

**Test Parameters**:
- `cpu_chunk_allocation_size_mask`: Can restrict CPU allocation sizes for testing
- Used in unit tests to verify page size policies

**Code Location**: `uvm_test_ioctl.h:607`

## Performance Characteristics

### 1. Page Table Overhead

**4KB Pages**:
- Maximum overhead: 512 PTEs per 2MB VA block
- Fine-grained control
- Higher TLB pressure

**64KB Big Pages**:
- Reduced overhead: 32 PTEs per 2MB VA block
- Moderate granularity
- Lower TLB pressure

**128KB Big Pages**:
- Further reduced: 16 PTEs per 2MB VA block
- Coarser granularity
- Even lower TLB pressure

**2MB Pages**:
- Minimum overhead: 1 PDE per 2MB VA block
- No granularity
- Lowest TLB pressure

### 2. TLB Efficiency

**TLB Coverage**:
- Larger pages = better TLB coverage
- Fewer TLB misses with big pages
- Critical for performance-sensitive workloads

**Example**:
- 4KB pages: 512 TLB entries needed for 2MB
- 2MB pages: 1 TLB entry for 2MB
- **512x reduction in TLB entries**

### 3. Memory Waste

**Big Page Trade-off**:
- Unused portions of big pages waste memory
- 4KB pages minimize waste
- Policy balances waste vs. performance

**Example**:
- 2MB page for 4KB allocation: 99.8% waste
- 4KB page for 4KB allocation: 0% waste
- Policy avoids big pages for small allocations

## Code References

### Key Files

- **Page size selection**: `uvm_va_block.c:1020-1120`
- **Chunk size initialization**: `uvm_mmu.c:2429-2448`
- **PTE splitting**: `uvm_va_block.c:6222-6238`
- **PTE merging**: `uvm_va_block.c:6445-6507`
- **2MB handling**: `uvm_va_block.c:6636-6681`
- **Architecture HALs**: `uvm_volta_mmu.c`, `uvm_pascal_mmu.c`, etc.

### Key Functions

- `uvm_va_block_gpu_chunk_index_range()`: Selects chunk size for mapping
- `block_calculate_largest_alloc_size()`: Calculates optimal allocation size
- `block_gpu_pte_big_split_write_4k()`: Splits big PTEs to 4KB
- `block_gpu_pte_merge_big_and_end()`: Merges 4KB PTEs to big pages
- `uvm_mmu_init_gpu_chunk_sizes()`: Initializes supported chunk sizes
- `uvm_mmu_init_gpu_va_space()`: Sets big page size for GPU VA space

## Summary

The UVM driver implements a sophisticated page size policy system that:

1. **Prefers larger page sizes** when alignment and size constraints allow
2. **Dynamically splits/merges** PTEs based on permission changes and migration needs
3. **Architecture-aware** selection based on GPU capabilities
4. **Performance-optimized** to minimize TLB misses and page table overhead
5. **Memory-efficient** balancing between waste and performance

The policies are largely automatic and transparent to users, with UVM making optimal choices based on allocation patterns, alignment, and hardware capabilities.
