# Page Mapping Promotion Algorithm

## Overview

**Yes, page mappings are automatically merged and promoted to larger page sizes** when more pages are faulted. The UVM driver uses an **opportunistic promotion algorithm** that merges smaller PTEs (Page Table Entries) into larger ones when conditions are met.

## Promotion Hierarchy

```
4KB PTEs → Big PTEs (64KB/128KB) → 2MB PTE
```

**Promotion Levels**:
1. **4KB → Big Page** (64KB or 128KB, depending on GPU)
2. **Big Page → 2MB** (if entire VA block is mapped)
3. **4KB → 2MB** (direct promotion if entire block is mapped)

## When Promotion Occurs

**Promotion happens automatically** during every mapping operation:
- When new pages are faulted and mapped
- When permissions are upgraded (e.g., READ → WRITE)
- When pages are migrated to a new location

**Key Point**: Promotion is **checked on every mapping operation**, not just when faults occur.

## Promotion Algorithm

### High-Level Flow

```
Every Mapping Operation:
  ↓
block_gpu_map_gpu() / block_map_gpu()
  ↓
block_gpu_compute_new_pte_state()
  → Computes desired page size for each region
  → Checks if promotion is possible
  ↓
block_gpu_map_big_and_4k() / block_gpu_map_to_2m()
  → Compares current state vs. desired state
  → Identifies regions that can be promoted
  → Performs merge operations
```

### Step 1: Compute Desired Page Size

**Function**: `block_gpu_compute_new_pte_state()` (`uvm_va_block.c:7562-7662`)

**Algorithm**:

```c
// For each page being mapped:
for_each_va_block_page_in_region_mask(page_index, pages_changing, big_region_all) {
    big_page_index = uvm_va_block_big_page_index(block, page_index, big_page_size);
    big_page_region = uvm_va_block_big_page_region(block, big_page_index, big_page_size);
    
    // Check if ALL pages in big_page_region are being mapped
    if (can_make_new_big_ptes &&
        uvm_page_mask_region_full(page_mask_after, big_page_region) &&
        (!UVM_ID_IS_CPU(resident_id) ||
         (uvm_cpu_chunk_get_size(chunk) >= big_page_size &&
          uvm_va_block_cpu_is_region_resident_on(block, nid, big_page_region)))) {
        __set_bit(big_page_index, new_pte_state->big_ptes);  // PROMOTION!
    }
}
```

**Key Conditions for Promotion**:

1. **All Pages Mapped**: `uvm_page_mask_region_full(page_mask_after, big_page_region)`
   - **Critical**: ALL pages in the big page region must be mapped
   - Example: For 64KB big page, all 16 pages (16 × 4KB) must be mapped

2. **Physical Contiguity** (for CPU memory):
   - CPU chunk size >= big_page_size
   - All pages resident on same NUMA node

3. **GPU Support**: GPU must support big pages for this memory type

**Evidence**: `uvm_va_block.c:7654-7659`

---

### Step 2: Identify Promotion Opportunities

**Function**: `block_gpu_map_big_and_4k()` (`uvm_va_block.c:7103-7270`)

**Promotion Detection**:

```c
// Case 2: Merge currently-4k PTEs to big with new_prot
// Mask computation: !big_before && big_after
if (bitmap_andnot(big_ptes_merge, new_pte_state->big_ptes, gpu_state->big_ptes, MAX_BIG_PAGES_PER_UVM_VA_BLOCK)) {
    // PROMOTION DETECTED!
    // big_ptes_merge contains big pages that are NOW big but WERE NOT big before
    block_gpu_pte_merge_big_and_end(...);
}
```

**What This Does**:
- `new_pte_state->big_ptes`: Desired state (which pages SHOULD be big)
- `gpu_state->big_ptes`: Current state (which pages ARE big)
- `big_ptes_merge = new & !old`: Pages that need promotion

**Evidence**: `uvm_va_block.c:7219` - Promotion detection logic

---

### Step 3: Perform Promotion (4KB → Big Page)

**Function**: `block_gpu_pte_merge_big_and_end()` (`uvm_va_block.c:6449-6517`)

**Algorithm**:

```c
// Step 1: Write big PTE as "unmapped" to disable 4K PTEs
block_gpu_pte_clear_big(block, gpu, big_ptes_to_merge, unmapped_pte_val, pte_batch, tlb_batch);

// Step 2: Invalidate TLB entries for both big and 4K sizes
for_each_set_bit(big_page_index, big_ptes_to_merge, MAX_BIG_PAGES_PER_UVM_VA_BLOCK) {
    uvm_tlb_batch_invalidate(tlb_batch,
                             uvm_va_block_big_page_addr(block, big_page_index, big_page_size),
                             big_page_size,
                             big_page_size | UVM_PAGE_SIZE_4K,  // Invalidate both!
                             UVM_MEMBAR_NONE);
}

// Step 3: End batches (commits changes)
uvm_pte_batch_end(pte_batch);
uvm_tlb_batch_end(tlb_batch, push, tlb_membar);

// Step 4: Write big PTE with new permissions (done in caller)
block_gpu_pte_write_big(block, gpu, resident_id, new_prot, big_ptes_merge, pte_batch, tlb_batch);
```

**Why Two-Step Process**:
- **Cannot directly transition** from valid 4K PTEs to valid big PTE
- GPU TLBs might cache same VA in different cache lines
- Would violate memory ordering guarantees
- **Solution**: Transition through "unmapped" state

**Evidence**: `uvm_va_block.c:6478-6484` - Comment explains why two-step merge is needed

---

### Step 4: Promotion to 2MB

**Function**: `block_gpu_map_to_2m()` (`uvm_va_block.c:6772-6807`)

**Conditions for 2MB Promotion**:

```c
// Checked in block_gpu_compute_new_pte_state():
if (block_gpu_supports_2m(block, gpu) && 
    uvm_page_mask_full(page_mask_after) &&  // ALL pages in VA block mapped
    (UVM_ID_IS_INVALID(resident_id) ||
     is_block_phys_contig(block, resident_id, ...))) {  // Physically contiguous
    new_pte_state->pte_is_2m = true;
    return;
}
```

**Promotion Process**:

```c
// If currently using big/4K PTEs, merge them first
if (!gpu_state->pte_is_2m) {
    block_gpu_pte_merge_2m(block, block_context, gpu, push, UVM_MEMBAR_NONE);
    gpu_state->pte_is_2m = true;
    bitmap_zero(gpu_state->big_ptes, MAX_BIG_PAGES_PER_UVM_VA_BLOCK);
}

// Write 2MB PTE
block_gpu_pte_write_2m(block, gpu, resident_id, new_prot, pte_batch, tlb_batch);
```

**Evidence**: `uvm_va_block.c:7599-7605` (2MB check), `uvm_va_block.c:6790-6795` (merge to 2MB)

---

## Promotion Scenarios

### Scenario 1: Sequential Page Faults (4KB → Big Page)

```
Initial State:
  Pages 0-3: Mapped as 4KB PTEs
  Pages 4-15: Unmapped

Fault on Page 4:
  → Maps page 4 as 4KB PTE
  → Cannot promote (pages 5-15 not mapped)

Fault on Page 5:
  → Maps page 5 as 4KB PTE
  → Cannot promote (pages 6-15 not mapped)

... (faults continue) ...

Fault on Page 15:
  → Maps page 15 as 4KB PTE
  → PROMOTION CHECK:
     - All pages 0-15 now mapped? YES ✅
     - Pages 0-15 form complete 64KB region? YES ✅
     - Physically contiguous? YES ✅
  → PROMOTION: Merge 16 × 4KB PTEs → 1 × 64KB big PTE
```

**Code Path**:
1. `block_gpu_compute_new_pte_state()` detects all pages in big_page_region are mapped
2. Sets `new_pte_state->big_ptes[0] = 1`
3. `block_gpu_map_big_and_4k()` detects `big_ptes_merge = {0}` (was 0, now 1)
4. Calls `block_gpu_pte_merge_big_and_end()` to merge

**Evidence**: `uvm_va_block.c:7654-7659` (promotion condition), `uvm_va_block.c:7219` (merge detection)

---

### Scenario 2: Batch Fault Processing (Multiple Promotions)

```
Initial State:
  VA Block: [0x1000000, 0x101FFFFF] (2MB)
  All pages: Unmapped

Batch Fault 1: Pages 0-15 (64KB region)
  → Maps as 16 × 4KB PTEs
  → PROMOTION: Merge to 1 × 64KB big PTE ✅

Batch Fault 2: Pages 16-31 (64KB region)
  → Maps as 16 × 4KB PTEs
  → PROMOTION: Merge to 1 × 64KB big PTE ✅

... (more batches) ...

Batch Fault 32: Pages 480-511 (final 64KB region)
  → Maps as 16 × 4KB PTEs
  → PROMOTION: Merge to 1 × 64KB big PTE ✅
  → FINAL CHECK: All pages in VA block mapped?
     - YES ✅
     - Physically contiguous? YES ✅
  → FINAL PROMOTION: Merge 32 × 64KB big PTEs → 1 × 2MB PTE ✅
```

**Evidence**: `uvm_va_block.c:7599-7605` (2MB promotion check)

---

### Scenario 3: Partial Promotion (Mixed Sizes)

```
Initial State:
  Pages 0-15: Mapped as 1 × 64KB big PTE
  Pages 16-31: Unmapped

Fault on Page 16:
  → Maps page 16 as 4KB PTE
  → Cannot promote pages 16-31 (pages 17-31 not mapped)

Fault on Page 17:
  → Maps page 17 as 4KB PTE
  → Cannot promote (pages 18-31 not mapped)

... (only pages 16-19 fault) ...

Final State:
  Pages 0-15: 1 × 64KB big PTE ✅
  Pages 16-19: 4 × 4KB PTEs ❌ (cannot promote - incomplete region)
  Pages 20-31: Unmapped
```

**Why No Promotion**: `uvm_page_mask_region_full()` returns FALSE because pages 20-31 are not mapped.

**Evidence**: `uvm_va_block.c:7655` - Requires ALL pages in region to be mapped

---

## Promotion Conditions Summary

### For 4KB → Big Page Promotion

**Required**:
1. ✅ All pages in big_page_region are mapped (`uvm_page_mask_region_full()`)
2. ✅ GPU supports big pages for this memory type
3. ✅ If CPU memory: Physically contiguous (chunk size >= big_page_size, same NUMA node)

**Not Required**:
- ❌ Pages must be faulted in order
- ❌ Pages must have same permissions (can promote during permission upgrade)
- ❌ Pages must be faulted in same batch

**Evidence**: `uvm_va_block.c:7654-7659`

---

### For Big Page → 2MB Promotion

**Required**:
1. ✅ GPU supports 2MB pages (`block_gpu_supports_2m()`)
2. ✅ **ALL pages in entire VA block are mapped** (`uvm_page_mask_full()`)
3. ✅ Memory is physically contiguous (`is_block_phys_contig()`)

**Evidence**: `uvm_va_block.c:7599-7605`

---

## Promotion During Permission Upgrades

**Promotion can occur even when no new pages are faulted**:

```
Initial State:
  Pages 0-15: Mapped as 16 × 4KB PTEs with READ permission

Upgrade Pages 0-15 to WRITE:
  → block_gpu_compute_new_pte_state() checks:
     - All pages 0-15 being upgraded? YES ✅
     - All pages in big_page_region? YES ✅
     - Can use big page? YES ✅
  → Sets new_pte_state->big_ptes[0] = 1
  → PROMOTION: Merge 16 × 4KB PTEs → 1 × 64KB big PTE
  → Write big PTE with WRITE permission
```

**Evidence**: `uvm_va_block.c:8493-8498` - Called on every mapping operation, including permission upgrades

---

## Promotion Algorithm Details

### Bitmap Operations

**Current State**: `gpu_state->big_ptes`
- Bitmap of which big pages are currently using big PTEs
- Example: `{0, 1, 0, 1}` means big pages 0 and 2 use big PTEs

**Desired State**: `new_pte_state->big_ptes`
- Bitmap of which big pages SHOULD use big PTEs after operation
- Computed by `block_gpu_compute_new_pte_state()`

**Promotion Detection**: `big_ptes_merge = new & !old`
- Pages that are NOW big but WERE NOT big before
- These need promotion

**Split Detection**: `big_ptes_split = old & !new`
- Pages that WERE big but NOW should be small
- These need splitting (demotion)

**Evidence**: `uvm_va_block.c:7145` (split), `uvm_va_block.c:7219` (merge)

---

### Two-Phase Merge Process

**Phase 1: Disable Lower-Level PTEs**
```c
// Write big PTE as "unmapped" (not invalid!)
block_gpu_pte_clear_big(..., unmapped_pte_val, ...);
```
- GPU MMU stops at unmapped big PTE
- Lower 4K PTEs are still valid but not accessed
- Prevents race conditions

**Phase 2: Invalidate and Write**
```c
// Invalidate TLB entries
uvm_tlb_batch_invalidate(..., big_page_size | UVM_PAGE_SIZE_4K, ...);

// Write big PTE with new permissions
block_gpu_pte_write_big(..., new_prot, ...);
```
- Invalidates both big and 4K TLB entries
- Writes final big PTE
- GPU MMU now uses big PTE

**Why Two Phases**: Prevents GPU from caching same VA in different TLB cache lines, which would violate memory ordering.

**Evidence**: `uvm_va_block.c:6478-6484` - Comment explains memory ordering concern

---

## Promotion Performance

### Benefits

1. **Fewer TLB Entries**: 1 big PTE vs. 16 small PTEs
2. **Better TLB Coverage**: Single entry covers larger address range
3. **Reduced Page Table Size**: Fewer PTEs to manage
4. **Faster MMU Lookups**: Fewer levels to traverse

### Costs

1. **Promotion Overhead**: Two-phase merge requires TLB invalidations
2. **Split Overhead**: If pages later need different permissions, must split
3. **Memory Contiguity Requirement**: May prevent promotion if memory fragmented

---

## Code Flow Diagram

```
Page Fault / Mapping Operation
  ↓
block_gpu_map_gpu()
  ↓
block_gpu_compute_new_pte_state()
  │
  ├─> Check 2MB promotion:
  │   if (all_pages_mapped && physically_contiguous):
  │       new_pte_state->pte_is_2m = true
  │       return
  │
  └─> Check big page promotion:
      for each big_page_region:
          if (all_pages_in_region_mapped && can_use_big_page):
              new_pte_state->big_ptes[big_page_index] = 1
  ↓
block_gpu_map_big_and_4k() / block_gpu_map_to_2m()
  │
  ├─> Detect promotions:
  │   big_ptes_merge = new_pte_state->big_ptes & !gpu_state->big_ptes
  │   (Pages that need promotion)
  │
  ├─> Detect splits:
  │   big_ptes_split = gpu_state->big_ptes & !new_pte_state->big_ptes
  │   (Pages that need demotion)
  │
  └─> Perform operations:
      if (big_ptes_merge):
          block_gpu_pte_merge_big_and_end()  // PROMOTION
      if (big_ptes_split):
          block_gpu_pte_big_split_write_4k()  // DEMOTION
      if (new_pte_state->pte_is_2m && !gpu_state->pte_is_2m):
          block_gpu_pte_merge_2m()  // PROMOTION TO 2MB
```

---

## Key Code References

### Promotion Detection

- **Function**: `block_gpu_compute_new_pte_state()` (`uvm_va_block.c:7562-7662`)
  - **Line 7654-7659**: Big page promotion condition
  - **Line 7599-7605**: 2MB promotion condition

### Promotion Execution

- **Function**: `block_gpu_map_big_and_4k()` (`uvm_va_block.c:7103-7270`)
  - **Line 7219**: Detection of pages to promote (`big_ptes_merge`)
  - **Line 7222**: Call to merge function

- **Function**: `block_gpu_pte_merge_big_and_end()` (`uvm_va_block.c:6449-6517`)
  - **Line 6484**: Write unmapped big PTE (Phase 1)
  - **Line 6489-6495**: TLB invalidation
  - **Line 7257**: Write final big PTE (Phase 2)

- **Function**: `block_gpu_map_to_2m()` (`uvm_va_block.c:6772-6807`)
  - **Line 6790-6795**: Merge big/4K PTEs to 2MB

- **Function**: `block_gpu_pte_merge_2m()` (`uvm_va_block.c:6681-6750`)
  - **Line 6700-6721**: Merge process for 2MB promotion

---

## Summary

### Promotion Behavior

✅ **YES**: Mappings are automatically promoted when:
- All pages in a big page region are mapped
- Memory is physically contiguous (for CPU memory)
- GPU supports the larger page size

✅ **Promotion happens**:
- On every mapping operation (not just faults)
- During permission upgrades
- During migrations
- Automatically and opportunistically

✅ **Promotion levels**:
- 4KB → Big Page (64KB/128KB): When region is complete
- Big Page → 2MB: When entire VA block is complete

### Algorithm Characteristics

- **Opportunistic**: Promotes whenever conditions are met
- **Automatic**: No explicit promotion API needed
- **Safe**: Two-phase merge prevents memory ordering violations
- **Efficient**: Reduces TLB entries and page table size

### Key Insight

**The promotion algorithm is integrated into the mapping logic itself**. Every time pages are mapped, the driver checks if promotion is possible and performs it automatically. This means that as more pages are faulted and mapped, they naturally coalesce into larger page sizes when alignment and contiguity conditions are met.
