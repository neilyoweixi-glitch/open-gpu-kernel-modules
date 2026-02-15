# Page Size Selection from Fault Address - Code Evidence

This document traces the complete code path from GPU fault address to final page size selection, with exact code references and line numbers.

## Complete Code Flow

```
GPU Fault Address (from hardware)
  ↓
[1] UVM_PAGE_ALIGN_DOWN() - Align fault address
  ↓
[2] Convert to page_index within VA block
  ↓
[3] block_gpu_compute_new_pte_state() - Determine page size
  ↓
[4] block_gpu_map_*() - Apply mapping with selected size
```

## Step-by-Step Evidence

### Step 1: Fault Address Alignment

**Location**: `kernel-open/nvidia-uvm/uvm_gpu_replayable_faults.c:917-919`

**Code**:
```c
// The GPU aligns the fault addresses to 4k, but all of our tracking is
// done in PAGE_SIZE chunks which might be larger.
current_entry->fault_address = UVM_PAGE_ALIGN_DOWN(current_entry->fault_address);
```

**Evidence**:
- **Line 917**: Comment explains GPU aligns to 4KB
- **Line 919**: Fault address is aligned down to PAGE_SIZE boundary
- **Purpose**: Ensures fault address matches UVM's page tracking granularity

**Macro Definition**: `kernel-open/nvidia-uvm/uvm_common.h:220`
```c
#define UVM_PAGE_ALIGN_DOWN(value) UVM_ALIGN_DOWN(value, PAGE_SIZE)
```

**UVM_ALIGN_DOWN Definition**: `kernel-open/nvidia-uvm/uvm_common.h:208-211`
```c
#define UVM_ALIGN_DOWN(x, a) ({         \
        typeof(x) _a = a;               \
        UVM_ASSERT(is_power_of_2(_a));  \
        (x) & ~(_a - 1);                \
```

**What This Does**:
- Rounds fault address down to nearest PAGE_SIZE boundary
- Example: `0x1234` → `0x1000` (if PAGE_SIZE = 4KB)
- Example: `0x10000` → `0x10000` (already aligned)

---

### Step 2: Fault Address → Page Index

**Location**: `kernel-open/nvidia-uvm/uvm_gpu_replayable_faults.c:1375-1586`

**Code Flow**:
```c
// service_fault_batch_block_locked() processes faults
static NV_STATUS service_fault_batch_block_locked(...)
{
    // ...
    for (i = first_fault_index; i < batch_context->num_coalesced_faults; ++i) {
        uvm_fault_buffer_entry_t *fault_entry = batch_context->ordered_fault_cache[i];
        
        // fault_entry->fault_address is already PAGE_SIZE aligned
        first_page_index = uvm_va_block_cpu_page_index(va_block, fault_entry->fault_address);
        
        // ... process fault ...
    }
    
    // Eventually calls:
    status = uvm_va_block_service_locked(gpu->id, va_block, va_block_retry, block_context);
}
```

**Page Index Calculation**: `kernel-open/nvidia-uvm/uvm_va_block.h:1614`
```c
static uvm_page_index_t uvm_va_block_cpu_page_index(uvm_va_block_t *va_block, NvU64 addr)
{
    return (uvm_page_index_t)((addr - va_block->start) / PAGE_SIZE);
}
```

**Evidence**:
- **Line 1614**: Converts fault address to page index within VA block
- **Formula**: `(fault_address - block_start) / PAGE_SIZE`
- **Result**: `page_index` used for all subsequent operations

---

### Step 3: Page Size Selection Algorithm

**Location**: `kernel-open/nvidia-uvm/uvm_va_block.c:7562-7662`

**Function**: `block_gpu_compute_new_pte_state()`

**Complete Code**:
```c
static void block_gpu_compute_new_pte_state(uvm_va_block_t *block,
                                            uvm_gpu_t *gpu,
                                            uvm_processor_id_t resident_id,
                                            const uvm_page_mask_t *pages_changing,
                                            const uvm_page_mask_t *page_mask_after,
                                            uvm_va_block_new_pte_state_t *new_pte_state)
{
    uvm_va_block_gpu_state_t *gpu_state = uvm_va_block_gpu_state_get(block, gpu->id);
    uvm_va_block_region_t big_region_all, big_page_region, region;
    NvU64 big_page_size;
    uvm_page_index_t page_index;
    size_t big_page_index;
    DECLARE_BITMAP(big_ptes_not_covered, MAX_BIG_PAGES_PER_UVM_VA_BLOCK);
    bool can_make_new_big_ptes;

    memset(new_pte_state, 0, sizeof(*new_pte_state));
    new_pte_state->needs_4k = true;

    // TODO: Bug 1676485: Force a specific page size for perf testing
    if (gpu_state->force_4k_ptes)
        return;

    // Limit HMM GPU allocations to PAGE_SIZE since migrate_vma_*(),
    // hmm_range_fault(), and make_device_exclusive_range() don't handle folios
    // yet. Also, it makes mremap() difficult since the new address may not
    // align with the GPU block size otherwise.
    // If PAGE_SIZE is 64K, the code following this check is OK since 64K
    // big_pages is supported on all HMM supported GPUs (Turing+).
    // TODO: Bug 3368756: add support for transparent huge pages (THP).
    if (uvm_va_block_is_hmm(block) && PAGE_SIZE == UVM_PAGE_SIZE_4K)
        return;

    UVM_ASSERT(uvm_page_mask_subset(pages_changing, page_mask_after));

    // If all pages in the 2M mask have the same attributes after the
    // operation is applied, we can use a 2M PTE.
    if (block_gpu_supports_2m(block, gpu) && uvm_page_mask_full(page_mask_after) &&
        (UVM_ID_IS_INVALID(resident_id) ||
         is_block_phys_contig(block, resident_id, block_get_page_node_residency(block, 0)))) {
        new_pte_state->pte_is_2m = true;
        new_pte_state->needs_4k = false;
        return;
    }

    // Find big PTEs with matching attributes

    // Can this block fit any big pages?
    big_page_size = uvm_va_block_gpu_big_page_size(block, gpu);
    big_region_all = uvm_va_block_big_page_region_all(block, big_page_size);
    if (big_region_all.first >= big_region_all.outer)
        return;

    new_pte_state->needs_4k = false;

    can_make_new_big_ptes = true;

    // Big pages can be used when mapping sysmem if the GPU supports it (Pascal+).
    if (UVM_ID_IS_CPU(resident_id) && !gpu->parent->can_map_sysmem_with_large_pages)
        can_make_new_big_ptes = false;

    // We must not fail during teardown: unmap (resident_id == UVM_ID_INVALID)
    // with no splits required. That means we should avoid allocating PTEs
    // which are only needed for merges.
    //
    // This only matters if we're merging to big PTEs. If we're merging to 2M,
    // then we must already have the 2M level (since it has to be allocated
    // before the lower levels).
    //
    // If pte_is_2m already and we don't have a big table, we're splitting so we
    // have to allocate.
    if (UVM_ID_IS_INVALID(resident_id) && !gpu_state->page_table_range_big.table && !gpu_state->pte_is_2m)
        can_make_new_big_ptes = false;

    for_each_va_block_page_in_region_mask(page_index, pages_changing, big_region_all) {
        uvm_cpu_chunk_t *chunk = NULL;
        int nid = NUMA_NO_NODE;

        if (UVM_ID_IS_CPU(resident_id)) {
            nid = block_get_page_node_residency(block, page_index);
            UVM_ASSERT(nid != NUMA_NO_NODE);
            chunk = uvm_cpu_chunk_get_chunk_for_page(block, nid, page_index);
        }

        big_page_index = uvm_va_block_big_page_index(block, page_index, big_page_size);
        big_page_region = uvm_va_block_big_page_region(block, big_page_index, big_page_size);

        __set_bit(big_page_index, new_pte_state->big_ptes_covered);

        // When mapping sysmem, we can use big pages only if we are mapping all
        // pages in the big page subregion and the CPU pages backing the
        // subregion are physically contiguous.
        if (can_make_new_big_ptes &&
            uvm_page_mask_region_full(page_mask_after, big_page_region) &&
            (!UVM_ID_IS_CPU(resident_id) ||
             (uvm_cpu_chunk_get_size(chunk) >= big_page_size &&
              uvm_va_block_cpu_is_region_resident_on(block, nid, big_page_region))))
            __set_bit(big_page_index, new_pte_state->big_ptes);

        if (!test_bit(big_page_index, new_pte_state->big_ptes))
            new_pte_state->needs_4k = true;
    }
}
```

**Key Selection Logic**:

#### 3.1: Check for 2MB Page Size

**Lines 7599-7605**:
```c
// If all pages in the 2M mask have the same attributes after the
// operation is applied, we can use a 2M PTE.
if (block_gpu_supports_2m(block, gpu) && uvm_page_mask_full(page_mask_after) &&
    (UVM_ID_IS_INVALID(resident_id) ||
     is_block_phys_contig(block, resident_id, block_get_page_node_residency(block, 0)))) {
    new_pte_state->pte_is_2m = true;
    new_pte_state->needs_4k = false;
    return;
}
```

**Conditions for 2MB**:
1. GPU supports 2MB (`block_gpu_supports_2m()`)
2. All pages in VA block are being mapped (`uvm_page_mask_full()`)
3. Memory is physically contiguous (`is_block_phys_contig()`)

**Evidence**: **Lines 7599-7605** - Early return if 2MB can be used

---

#### 3.2: Determine Big Page Size

**Line 7610**:
```c
big_page_size = uvm_va_block_gpu_big_page_size(block, gpu);
```

**Function**: `kernel-open/nvidia-uvm/uvm_va_block.c:2087-2093`
```c
NvU64 uvm_va_block_gpu_big_page_size(uvm_va_block_t *va_block, uvm_gpu_t *gpu)
{
    uvm_gpu_va_space_t *gpu_va_space;
    gpu_va_space = uvm_va_block_get_gpu_va_space(va_block, gpu);
    return gpu_va_space->page_tables.big_page_size;
}
```

**Evidence**: **Line 7610** - Gets GPU's preferred big page size (typically 128KB for Volta+, 64KB for Pascal)

---

#### 3.3: Calculate Big Page Region for Fault Address

**Lines 7646-7647**:
```c
big_page_index = uvm_va_block_big_page_index(block, page_index, big_page_size);
big_page_region = uvm_va_block_big_page_region(block, big_page_index, big_page_size);
```

**Function**: `kernel-open/nvidia-uvm/uvm_va_block.c:2120-2138`
```c
uvm_va_block_region_t uvm_va_block_big_page_region_subset(uvm_va_block_t *va_block,
                                                          uvm_va_block_region_t region,
                                                          NvU64 big_page_size)
{
    NvU64 start = uvm_va_block_region_start(va_block, region);
    NvU64 end = uvm_va_block_region_end(va_block, region);
    uvm_va_block_region_t big_region;

    UVM_ASSERT(start < va_block->end);
    UVM_ASSERT(end <= va_block->end);

    big_region = range_big_page_region_all(start, end, big_page_size);
    if (big_region.outer) {
        big_region.first += region.first;
        big_region.outer += region.first;
    }

    return big_region;
}
```

**Helper Function**: `kernel-open/nvidia-uvm/uvm_va_block.c:2095-2107`
```c
static uvm_va_block_region_t range_big_page_region_all(NvU64 start, NvU64 end, NvU64 big_page_size)
{
    NvU64 first_addr = UVM_ALIGN_UP(start, big_page_size);
    NvU64 outer_addr = UVM_ALIGN_DOWN(end + 1, big_page_size);

    // The range must fit within a VA block
    UVM_ASSERT(UVM_VA_BLOCK_ALIGN_DOWN(start) == UVM_VA_BLOCK_ALIGN_DOWN(end));

    if (outer_addr <= first_addr)
        return uvm_va_block_region(0, 0);

    return uvm_va_block_region((first_addr - start) / PAGE_SIZE, (outer_addr - start) / PAGE_SIZE);
}
```

**Evidence**: **Lines 7646-7647** - Calculates which big page region contains the faulting page

**Key Calculation**:
- `first_addr = UVM_ALIGN_UP(start, big_page_size)` - Round up to big page boundary
- `outer_addr = UVM_ALIGN_DOWN(end + 1, big_page_size)` - Round down to big page boundary
- **This determines alignment**: If fault address is aligned to big_page_size, it can use big pages

---

#### 3.4: Check if Big Page Can Be Used

**Lines 7654-7659**:
```c
// When mapping sysmem, we can use big pages only if we are mapping all
// pages in the big page subregion and the CPU pages backing the
// subregion are physically contiguous.
if (can_make_new_big_ptes &&
    uvm_page_mask_region_full(page_mask_after, big_page_region) &&
    (!UVM_ID_IS_CPU(resident_id) ||
     (uvm_cpu_chunk_get_size(chunk) >= big_page_size &&
      uvm_va_block_cpu_is_region_resident_on(block, nid, big_page_region))))
    __set_bit(big_page_index, new_pte_state->big_ptes);
```

**Conditions for Big Page**:
1. `can_make_new_big_ptes` - GPU supports big pages for this memory type
2. `uvm_page_mask_region_full(page_mask_after, big_page_region)` - **All pages in big page region are being mapped**
3. If CPU memory: chunk size >= big_page_size AND pages are resident on same NUMA node

**Evidence**: **Lines 7654-7659** - Sets bit in `big_ptes` bitmap if big page can be used

**Key Point**: **Line 7655** - `uvm_page_mask_region_full()` checks if **all pages** in the big page region are being mapped. This is the critical alignment check!

---

#### 3.5: Fallback to 4KB

**Lines 7661-7662**:
```c
if (!test_bit(big_page_index, new_pte_state->big_ptes))
    new_pte_state->needs_4k = true;
```

**Evidence**: **Lines 7661-7662** - If big page cannot be used, fall back to 4KB

---

### Step 4: Apply Selected Page Size

**Location**: `kernel-open/nvidia-uvm/uvm_va_block.c:8493-8537`

**Code**:
```c
block_gpu_compute_new_pte_state(va_block,
                                gpu,
                                resident_id,
                                pages_to_map,
                                &block_context->scratch_page_mask,
                                new_pte_state);

// ... allocate PTEs ...

pte_op = BLOCK_PTE_OP_MAP;
if (new_pte_state->pte_is_2m) {
    // We're either modifying permissions of a pre-existing 2M PTE, or all
    // permissions match so we can merge to a new 2M PTE.
    block_gpu_map_to_2m(va_block, block_context, gpu, resident_id, new_prot, &push, pte_op);
}
else if (gpu_state->pte_is_2m) {
    // Permissions on a subset of the existing 2M PTE are being upgraded, so
    // we have to split it into the appropriate mix of big and 4k PTEs.
    block_gpu_map_split_2m(va_block, block_context, gpu, resident_id, pages_to_map, new_prot, &push, pte_op);
}
else {
    // We're upgrading permissions on some pre-existing mix of big and 4K
    // PTEs into some other mix of big and 4K PTEs.
    block_gpu_map_big_and_4k(va_block, block_context, gpu, resident_id, pages_to_map, new_prot, &push, pte_op);
}
```

**Evidence**: **Lines 8523-8537** - Uses `new_pte_state->pte_is_2m` and `new_pte_state->big_ptes` to determine mapping function

---

## Critical Alignment Check

### The Key Function: `uvm_page_mask_region_full()`

**Location**: `kernel-open/nvidia-uvm/uvm_va_block.h` (inline function)

**Purpose**: Checks if all pages in a region are set in a page mask

**Usage**: **Line 7655** in `block_gpu_compute_new_pte_state()`

**What It Checks**:
- If fault address is `0x10000` (64KB aligned)
- And big_page_size is `0x10000` (64KB)
- Then `big_page_region` covers pages [0x10000, 0x1FFFF]
- **Big page can be used ONLY if ALL pages in [0x10000, 0x1FFFF] are being mapped**

**This is the alignment requirement**: The fault address must be aligned to big_page_size, AND all pages in that big page region must be mapped.

---

## Example Trace

### Example 1: 64KB-Aligned Fault Address

```
Fault Address: 0x10000 (64KB aligned)
PAGE_SIZE: 4KB

Step 1: Align
  fault_address = UVM_PAGE_ALIGN_DOWN(0x10000) = 0x10000 ✅

Step 2: Page Index
  page_index = (0x10000 - block_start) / 4096
  Assume block_start = 0x10000
  page_index = 0

Step 3: Big Page Check
  big_page_size = 0x10000 (64KB)
  big_page_index = uvm_va_block_big_page_index(block, 0, 0x10000) = 0
  big_page_region = [0, 15] (16 pages = 64KB)
  
  Check: uvm_page_mask_region_full(page_mask_after, big_page_region)
    → Checks if pages 0-15 are ALL in page_mask_after
    → If YES: Use 64KB big page ✅
    → If NO: Use 4KB pages ❌

Step 4: Apply
  If big page: block_gpu_map_big_and_4k() with big_ptes[0] = 1
  If not: block_gpu_map_big_and_4k() with big_ptes[0] = 0 (uses 4KB)
```

### Example 2: Misaligned Fault Address

```
Fault Address: 0x10004 (NOT aligned to 64KB)
PAGE_SIZE: 4KB

Step 1: Align
  fault_address = UVM_PAGE_ALIGN_DOWN(0x10004) = 0x10000 ✅
  (Aligned to PAGE_SIZE, not big_page_size)

Step 2: Page Index
  page_index = (0x10000 - block_start) / 4096 = 0

Step 3: Big Page Check
  big_page_size = 0x10000 (64KB)
  big_page_index = 0
  big_page_region = [0, 15] (16 pages)
  
  Check: uvm_page_mask_region_full(page_mask_after, big_page_region)
    → page_mask_after likely only has page 0 (the faulting page)
    → Pages 1-15 are NOT in page_mask_after
    → Result: FALSE ❌
    → Cannot use big page

Step 4: Apply
  block_gpu_map_big_and_4k() with big_ptes[0] = 0
  → Uses 4KB page size
```

---

## Summary of Evidence

### Key Code Locations

1. **Fault Address Alignment**: `uvm_gpu_replayable_faults.c:919`
   - Aligns fault address to PAGE_SIZE

2. **Page Size Selection**: `uvm_va_block.c:7562-7662`
   - `block_gpu_compute_new_pte_state()` - Main selection algorithm

3. **2MB Check**: `uvm_va_block.c:7599-7605`
   - Early return if entire VA block can use 2MB

4. **Big Page Check**: `uvm_va_block.c:7654-7659`
   - Checks alignment via `uvm_page_mask_region_full()`

5. **Alignment Calculation**: `uvm_va_block.c:2095-2107`
   - `range_big_page_region_all()` - Calculates aligned big page regions

6. **Mapping Application**: `uvm_va_block.c:8523-8537`
   - Uses selected page size to map pages

### Selection Algorithm

```
Given fault address:
  1. Align to PAGE_SIZE
  2. Convert to page_index
  3. Check if entire VA block can use 2MB:
     → If YES: Use 2MB
  4. Calculate big_page_region containing page_index
  5. Check if ALL pages in big_page_region are being mapped:
     → If YES: Use big_page_size (64KB/128KB)
     → If NO: Use 4KB
```

### Alignment Requirement

**The critical check is**: `uvm_page_mask_region_full(page_mask_after, big_page_region)`

This checks if **all pages** in the big page region are being mapped. For a fault address to use a big page:
- The fault address must be aligned to big_page_size
- **AND** all pages in that big page region must be mapped (not just the faulting page)

This is why misaligned addresses cannot use big pages: they don't map the entire big page region.
