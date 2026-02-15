# Tree-Based Page Fault Policy

## Overview

**Yes, there is a tree-based page fault policy** in the UVM driver. It's called the **Prefetch Bitmap Tree** and is used for intelligent prefetching of pages based on fault patterns and hierarchical analysis.

## Purpose

The tree-based policy enables **adaptive prefetching** by:
- Tracking fault patterns at multiple granularities (hierarchical levels)
- Identifying regions with high fault density
- Prefetching pages that are likely to be accessed soon
- Optimizing prefetch granularity based on access patterns

## Data Structure: Prefetch Bitmap Tree

### Structure Definition

**Location**: `kernel-open/nvidia-uvm/uvm_perf_prefetch.h:41-50`

```c
typedef struct
{
    uvm_page_mask_t pages;      // Bitmap of pages (leaf nodes)
    uvm_page_index_t offset;    // Offset for alignment
    NvU16 leaf_count;            // Number of leaf nodes (pages)
    NvU8 level_count;           // Number of tree levels
} uvm_perf_prefetch_bitmap_tree_t;
```

**Tree Structure**:
- **Leaves**: Individual pages (4KB granularity)
- **Internal Nodes**: Aggregated counters for subregions
- **Levels**: Hierarchical levels from leaves to root
- **Level Count**: `ilog2(roundup_pow_of_two(leaf_count)) + 1`

**Evidence**: `uvm_perf_prefetch.h:38-50` - Structure definition and comments

---

## Tree Construction

### Initialization

**Function**: `init_bitmap_tree_from_region()` (`uvm_perf_prefetch.c:222-238`)

```c
static void init_bitmap_tree_from_region(uvm_perf_prefetch_bitmap_tree_t *bitmap_tree,
                                         uvm_va_block_region_t max_prefetch_region,
                                         const uvm_page_mask_t *resident_mask,
                                         const uvm_page_mask_t *faulted_pages)
{
    // Initialize bitmap with resident and faulted pages
    if (resident_mask)
        uvm_page_mask_or(&bitmap_tree->pages, resident_mask, faulted_pages);
    else
        uvm_page_mask_copy(&bitmap_tree->pages, faulted_pages);

    // Shift bitmap to align with region
    uvm_page_mask_shift_right(&bitmap_tree->pages, &bitmap_tree->pages, max_prefetch_region.first);

    bitmap_tree->offset = 0;
    bitmap_tree->leaf_count = uvm_va_block_region_num_pages(max_prefetch_region);
    bitmap_tree->level_count = ilog2(roundup_pow_of_two(bitmap_tree->leaf_count)) + 1;
}
```

**Tree Levels Calculation**:
- `level_count = ilog2(roundup_pow_of_two(leaf_count)) + 1`
- Example: 512 pages → `ilog2(512) + 1 = 9 + 1 = 10` levels
- Each level represents a different granularity

**Evidence**: `uvm_perf_prefetch.c:237` - Level count calculation

---

## Tree Traversal Algorithm

### Iterator-Based Traversal

**Macro**: `uvm_perf_prefetch_bitmap_tree_traverse_counters()` (`uvm_perf_prefetch.h:108-113`)

```c
#define uvm_perf_prefetch_bitmap_tree_traverse_counters(counter,tree,page,iter) \
    for (uvm_perf_prefetch_bitmap_tree_iter_init((tree), (page), (iter)),       \
         (counter) = uvm_perf_prefetch_bitmap_tree_iter_get_count((tree), (iter)); \
         (iter)->level_idx >= 0;                                                 \
         (counter) = --(iter)->level_idx < 0? 0:                                \
                      uvm_perf_prefetch_bitmap_tree_iter_get_count((tree), (iter)))
```

**Traversal Direction**: **Bottom-up** (from leaf to root)
- Starts at leaf level (highest level index)
- Moves up tree levels (decreasing level index)
- At each level, computes counter for that subregion

**Evidence**: `uvm_perf_prefetch.h:108-113` - Traversal macro

---

### Counter Computation

**Function**: `uvm_perf_prefetch_bitmap_tree_iter_get_count()` (`uvm_perf_prefetch.c:94-100`)

```c
NvU16 uvm_perf_prefetch_bitmap_tree_iter_get_count(const uvm_perf_prefetch_bitmap_tree_t *bitmap_tree,
                                                   const uvm_perf_prefetch_bitmap_tree_iter_t *iter)
{
    uvm_va_block_region_t subregion = uvm_perf_prefetch_bitmap_tree_iter_get_range(bitmap_tree, iter);
    return uvm_page_mask_region_weight(&bitmap_tree->pages, subregion);
}
```

**What It Does**:
- Gets the region covered by current tree node
- Counts number of pages set in bitmap for that region
- Returns counter value for that level

**Evidence**: `uvm_perf_prefetch.c:94-100` - Counter computation

---

## Prefetch Region Computation

### Algorithm

**Function**: `compute_prefetch_region()` (`uvm_perf_prefetch.c:102-146`)

```c
static uvm_va_block_region_t compute_prefetch_region(uvm_page_index_t page_index,
                                                     uvm_perf_prefetch_bitmap_tree_t *bitmap_tree,
                                                     uvm_va_block_region_t max_prefetch_region)
{
    NvU16 counter;
    uvm_perf_prefetch_bitmap_tree_iter_t iter;
    uvm_va_block_region_t prefetch_region = uvm_va_block_region(0, 0);

    // Traverse tree bottom-up (from leaf to root)
    uvm_perf_prefetch_bitmap_tree_traverse_counters(counter,
                                                    bitmap_tree,
                                                    page_index - max_prefetch_region.first + bitmap_tree->offset,
                                                    &iter) {
        uvm_va_block_region_t subregion = uvm_perf_prefetch_bitmap_tree_iter_get_range(bitmap_tree, &iter);
        NvU16 subregion_pages = uvm_va_block_region_num_pages(subregion);

        UVM_ASSERT(counter <= subregion_pages);
        
        // Check if threshold is met
        if (counter * 100 > subregion_pages * g_uvm_perf_prefetch_threshold)
            prefetch_region = subregion;  // Found largest qualifying region
    }

    return prefetch_region;
}
```

**Algorithm Steps**:

1. **Start at faulting page**: Initialize iterator at leaf level
2. **Traverse upward**: Move from leaf to root
3. **At each level**:
   - Get subregion covered by current node
   - Count pages in bitmap for that subregion
   - Check threshold: `counter * 100 > subregion_pages * threshold`
4. **Select largest qualifying region**: First region that meets threshold

**Threshold Check**:
- Default threshold: **51%** (`UVM_PREFETCH_THRESHOLD_DEFAULT = 51`)
- If 51% or more of pages in subregion are mapped/faulted → prefetch entire subregion
- **Greedy approach**: Selects largest qualifying region

**Evidence**: `uvm_perf_prefetch.c:118` - Threshold check

---

## Tree-Based Prefetch Policy

### Policy Overview

**Goal**: Prefetch pages based on fault density at multiple granularities

**Strategy**:
1. **Track fault patterns** in hierarchical tree
2. **Identify dense regions** at different granularities
3. **Prefetch entire subregions** when threshold is met
4. **Adapt granularity** based on access patterns

### Integration with Fault Handling

**Location**: `kernel-open/nvidia-uvm/uvm_va_block.c:11873-11926`

**Function**: `uvm_va_block_get_prefetch_hint()`

```c
static void uvm_va_block_get_prefetch_hint(uvm_va_block_t *va_block,
                                           const uvm_va_policy_t *policy,
                                           uvm_service_block_context_t *service_context)
{
    // ... 
    
    // Update prefetch tracking structure with the pages that will migrate
    // due to faults
    uvm_perf_prefetch_get_hint_va_block(va_block,
                                        service_context->block_context,
                                        new_residency,
                                        new_residency_mask,
                                        service_context->region,
                                        &service_context->prefetch_bitmap_tree,
                                        &service_context->prefetch_hint);
    
    // Prefetched pages are added to fault batch
    if (UVM_ID_IS_VALID(service_context->prefetch_hint.residency)) {
        const uvm_page_mask_t *prefetch_pages_mask = &service_context->prefetch_hint.prefetch_pages_mask;
        // ... add prefetch pages to batch ...
    }
}
```

**When Called**: During every fault batch processing

**Evidence**: `uvm_va_block.c:11891-11897` - Tree-based prefetch integration

---

## Tree Update Algorithm

### Growing Fault Granularity

**Function**: `grow_fault_granularity()` (`uvm_perf_prefetch.c:164-220`)

**Purpose**: Adjust tree to prefer big page granularity when appropriate

```c
static void grow_fault_granularity(uvm_perf_prefetch_bitmap_tree_t *bitmap_tree,
                                   NvU64 big_page_size,
                                   uvm_va_block_region_t big_pages_region,
                                   uvm_va_block_region_t max_prefetch_region,
                                   const uvm_page_mask_t *faulted_pages,
                                   const uvm_page_mask_t *thrashing_pages)
{
    // Migrate whole block if no big pages and no page in it is thrashing
    if (!big_pages_region.outer) {
        grow_fault_granularity_if_no_thrashing(bitmap_tree,
                                               max_prefetch_region,
                                               max_prefetch_region.first,
                                               faulted_pages,
                                               thrashing_pages);
        return;
    }

    // Migrate whole "prefix" if no page in it is thrashing
    if (big_pages_region.first > max_prefetch_region.first) {
        uvm_va_block_region_t prefix_region = uvm_va_block_region(max_prefetch_region.first, big_pages_region.first);
        grow_fault_granularity_if_no_thrashing(bitmap_tree, prefix_region, ...);
    }

    // Migrate whole big pages if they are not thrashing
    for (page_index = big_pages_region.first;
         page_index < big_pages_region.outer;
         page_index += pages_per_big_page) {
        uvm_va_block_region_t big_region = uvm_va_block_region(page_index, page_index + pages_per_big_page);
        grow_fault_granularity_if_no_thrashing(bitmap_tree, big_region, ...);
    }

    // Migrate whole "suffix" if no page in it is thrashing
    if (big_pages_region.outer < max_prefetch_region.outer) {
        uvm_va_block_region_t suffix_region = uvm_va_block_region(big_pages_region.outer, max_prefetch_region.outer);
        grow_fault_granularity_if_no_thrashing(bitmap_tree, suffix_region, ...);
    }
}
```

**Strategy**:
- **Prefers big page granularity**: If a big page region has faults and no thrashing, mark entire big page
- **Avoids thrashing**: Skips regions with thrashing pages
- **Handles misalignment**: Handles prefix/suffix regions separately

**Evidence**: `uvm_perf_prefetch.c:164-220` - Granularity growth algorithm

---

## Threshold-Based Prefetching

### Threshold Policy

**Default Threshold**: **51%** (`UVM_PREFETCH_THRESHOLD_DEFAULT = 51`)

**Configurable**: Module parameter `uvm_perf_prefetch_threshold` (1-100)

**Logic**:
```c
if (counter * 100 > subregion_pages * g_uvm_perf_prefetch_threshold)
    prefetch_region = subregion;
```

**Meaning**:
- If 51% or more of pages in a subregion are faulted/mapped
- Prefetch the **entire subregion** (including unmapped pages)

**Rationale**:
- High fault density indicates sequential/patterned access
- Prefetching entire region reduces future faults
- Threshold prevents over-prefetching sparse access patterns

**Evidence**: `uvm_perf_prefetch.c:42-48` - Threshold definition and comments

---

## Example: Tree-Based Prefetch

### Scenario: Sequential Access Pattern

```
VA Block: 512 pages (2MB)
Fault Pattern: Pages 0-15, 32-47, 64-79 (sequential 16-page regions)

Tree Structure (simplified):
Level 0 (Root):     [0-511]          Counter: 48/512 = 9% ❌
Level 1:            [0-255] [256-511] Counter: 32/256 = 12% ❌
Level 2:            [0-127] [128-255] Counter: 32/128 = 25% ❌
Level 3:            [0-63] [64-127]   Counter: 32/64 = 50% ❌
Level 4:            [0-31] [32-63]    Counter: 16/32 = 50% ❌
Level 5:            [0-15] [16-31]    Counter: 16/16 = 100% ✅
Level 6:            [32-47] [48-63]   Counter: 16/16 = 100% ✅
Level 7:            [64-79] [80-95]   Counter: 16/16 = 100% ✅

Fault on Page 0:
  → Traverse tree bottom-up
  → Level 5: [0-15] has 16/16 = 100% > 51% ✅
  → Prefetch region: [0-15] (16 pages)

Fault on Page 32:
  → Traverse tree bottom-up
  → Level 5: [32-47] has 16/16 = 100% > 51% ✅
  → Prefetch region: [32-47] (16 pages)

Fault on Page 64:
  → Traverse tree bottom-up
  → Level 5: [64-79] has 16/16 = 100% > 51% ✅
  → Prefetch region: [64-79] (16 pages)
```

**Result**: Each fault triggers prefetch of entire 16-page region

---

### Scenario: Sparse Access Pattern

```
VA Block: 512 pages
Fault Pattern: Pages 0, 100, 200, 300 (sparse, 4 pages total)

Tree Traversal for Page 0:
Level 0 (Root):     [0-511]          Counter: 4/512 = 0.8% ❌
Level 1:            [0-255] [256-511] Counter: 2/256 = 0.8% ❌
Level 2:            [0-127] [128-255] Counter: 2/128 = 1.6% ❌
Level 3:            [0-63] [64-127]  Counter: 1/64 = 1.6% ❌
...
Level 9 (Leaf):     [0]              Counter: 1/1 = 100% ✅

Result: Only prefetch single page [0] (no larger region meets threshold)
```

**Result**: Sparse patterns don't trigger large prefetches

---

## Configuration Parameters

### Tunable Parameters

**1. Prefetch Enable** (`uvm_perf_prefetch_enable`)
- Default: `1` (enabled)
- Module parameter: `uvm_perf_prefetch_enable`

**2. Prefetch Threshold** (`uvm_perf_prefetch_threshold`)
- Default: `51` (51%)
- Range: 1-100
- Module parameter: `uvm_perf_prefetch_threshold`
- **Lower threshold** → More aggressive prefetching
- **Higher threshold** → More conservative prefetching

**3. Minimum Faults** (`uvm_perf_prefetch_min_faults`)
- Default: `1`
- Range: 1-20
- Module parameter: `uvm_perf_prefetch_min_faults`
- Minimum number of faults before prefetching is enabled

**Evidence**: `uvm_perf_prefetch.c:38-61` - Parameter definitions

---

## Tree Alignment and Big Pages

### Big Page Optimization

**Function**: `update_bitmap_tree_from_va_block()` (`uvm_perf_prefetch.c:240-297`)

**Purpose**: Align tree to big page boundaries for better prefetching

```c
// Adjust the prefetch tree to big page granularity to make sure that we
// get big page-friendly prefetching hints
if (big_pages_region.first - max_prefetch_region.first > 0) {
    bitmap_tree->offset = big_page_size / PAGE_SIZE - (big_pages_region.first - max_prefetch_region.first);
    bitmap_tree->leaf_count = uvm_va_block_region_num_pages(max_prefetch_region) + bitmap_tree->offset;
    
    uvm_page_mask_shift_left(&bitmap_tree->pages, &bitmap_tree->pages, bitmap_tree->offset);
    bitmap_tree->level_count = ilog2(roundup_pow_of_two(bitmap_tree->leaf_count)) + 1;
}
```

**Strategy**:
- Aligns tree to big page boundaries (64KB/128KB)
- Ensures prefetch hints are big page-friendly
- Improves promotion to big page mappings

**Evidence**: `uvm_perf_prefetch.c:273-285` - Big page alignment

---

## Integration Points

### During Fault Processing

**Location**: `kernel-open/nvidia-uvm/uvm_va_block.c:12447`

```c
uvm_va_block_get_prefetch_hint(va_block,
                               uvm_va_policy_get_region(va_block, service_context->region),
                               service_context);
```

**When**: Called before processing each fault batch

**What It Does**:
1. Updates bitmap tree with faulted pages
2. Traverses tree to find prefetch regions
3. Adds prefetch pages to fault batch
4. Prefetched pages are migrated along with faulted pages

**Evidence**: `uvm_va_block.c:12447` - Prefetch hint call

---

## Performance Benefits

### Advantages

1. **Adaptive Granularity**: Automatically selects optimal prefetch size
2. **Pattern Detection**: Identifies sequential/patterned access
3. **Reduced Faults**: Prefetches likely-to-be-accessed pages
4. **Big Page Friendly**: Aligns with big page boundaries
5. **Thrashing Avoidance**: Skips prefetching in thrashing regions

### Trade-offs

1. **Memory Overhead**: Prefetched pages consume memory
2. **Migration Cost**: Prefetching requires data migration
3. **False Positives**: May prefetch pages that aren't accessed

---

## Code Flow Diagram

```
Page Fault Occurs
  ↓
uvm_va_block_service_locked()
  ↓
uvm_va_block_get_prefetch_hint()
  │
  ├─> Update bitmap_tree with faulted pages
  │   init_bitmap_tree_from_region()
  │   update_bitmap_tree_from_va_block()
  │
  ├─> Traverse tree bottom-up
  │   uvm_perf_prefetch_bitmap_tree_traverse_counters()
  │   │
  │   ├─> Level N (leaf): Check threshold
  │   ├─> Level N-1: Check threshold
  │   ├─> ...
  │   └─> Level 0 (root): Check threshold
  │
  ├─> Select largest qualifying region
  │   compute_prefetch_region()
  │   → Returns region where counter > threshold
  │
  └─> Add prefetch pages to fault batch
      → Prefetched pages migrated along with faulted pages
```

---

## Summary

### Tree-Based Policy Characteristics

✅ **Hierarchical Analysis**: Multi-level tree structure
✅ **Bottom-Up Traversal**: From leaf to root
✅ **Threshold-Based**: 51% threshold for prefetch decision
✅ **Adaptive Granularity**: Selects optimal prefetch size
✅ **Big Page Optimized**: Aligns with big page boundaries
✅ **Pattern Detection**: Identifies dense fault regions

### Key Functions

- **Tree Construction**: `init_bitmap_tree_from_region()` (`uvm_perf_prefetch.c:222`)
- **Tree Traversal**: `uvm_perf_prefetch_bitmap_tree_traverse_counters()` (`uvm_perf_prefetch.h:108`)
- **Prefetch Computation**: `compute_prefetch_region()` (`uvm_perf_prefetch.c:102`)
- **Integration**: `uvm_va_block_get_prefetch_hint()` (`uvm_va_block.c:11873`)

### Algorithm Essence

**The tree-based policy uses a hierarchical bitmap tree to analyze fault patterns at multiple granularities. By traversing from leaf to root, it identifies the largest subregion where fault density exceeds a threshold (51%), then prefetches the entire subregion. This enables adaptive, pattern-aware prefetching that optimizes for both small and large page sizes.**
