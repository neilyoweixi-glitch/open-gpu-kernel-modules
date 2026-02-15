# Address Alignment Explained

## What is Address Alignment?

**Address alignment** means that a memory address is divisible by a specific size (called the "alignment boundary"). An address is **aligned** to a size if the address modulo that size equals zero.

### Mathematical Definition

An address `addr` is **aligned** to size `size` if:
```
addr % size == 0
```

Or equivalently:
```
addr & (size - 1) == 0
```

### Simple Example

```
Address: 0x1000 (4096 decimal)
Size:    0x1000 (4KB = 4096 bytes)

Check: 0x1000 % 0x1000 = 0
Result: ✅ ALIGNED (address is divisible by size)

Address: 0x1001 (4097 decimal)
Size:    0x1000 (4KB = 4096 bytes)

Check: 0x1001 % 0x1000 = 1
Result: ❌ NOT ALIGNED (address is NOT divisible by size)
```

## Why Does Alignment Matter?

### Hardware Requirements

**Memory controllers and MMUs require alignment** for:
- **Efficient access**: Aligned accesses can be handled in single operations
- **Hardware constraints**: Page tables, TLBs, and caches work with aligned boundaries
- **Performance**: Misaligned accesses may require multiple operations

### GPU Memory Management

For GPU chunks, alignment is **mandatory** because:
- **Page tables**: GPU page table entries map aligned regions
- **TLB efficiency**: Translation lookaside buffers cache aligned translations
- **Memory controllers**: GPU memory controllers expect aligned chunks
- **DMA operations**: Direct memory access requires aligned buffers

## Alignment in UVM Code

### Alignment Macros

**UVM_ALIGN_DOWN** (round down to alignment boundary):
```c
#define UVM_ALIGN_DOWN(x, a) ((x) & ~(a - 1))
```

**UVM_ALIGN_UP** (round up to alignment boundary):
```c
#define UVM_ALIGN_UP(x, a) (((x) + a - 1) & ~(a - 1))
```

**How they work**:
- `a - 1` creates a mask of lower bits
- `~(a - 1)` clears those lower bits
- `& ~(a - 1)` rounds down to boundary
- `+ a - 1` before masking rounds up

### Examples

```
UVM_ALIGN_DOWN(0x1234, 0x1000) = 0x1000
  → Rounds 0x1234 down to nearest 4KB boundary

UVM_ALIGN_UP(0x1234, 0x1000) = 0x2000
  → Rounds 0x1234 up to nearest 4KB boundary

UVM_ALIGN_DOWN(0x20000, 0x10000) = 0x20000
  → Already aligned to 64KB, stays the same

UVM_ALIGN_UP(0x20001, 0x10000) = 0x30000
  → Rounds up to next 64KB boundary
```

## Alignment Detection Algorithm

### Code Location

**Function**: `block_gpu_chunk_size()` (`uvm_va_block.c:1183-1213`)

### Algorithm

```c
// Calculate which chunk sizes the start address is aligned to
start_alignments = start ^ (start - 1);
```

**How it works**:
- `start - 1` flips the rightmost 1 bit and all trailing 0s
- `start ^ (start - 1)` creates a mask of the rightmost 1 bit and all trailing 0s
- This mask represents all power-of-2 sizes that divide the address

### Step-by-Step Example

**Example 1: Address aligned to 4KB**
```
start = 0x1000 (4096 decimal, binary: 0001 0000 0000 0000)
start - 1 = 0x0FFF (4095 decimal, binary: 0000 1111 1111 1111)
start ^ (start - 1) = 0x1FFF (binary: 0001 1111 1111 1111)

This mask includes:
  - 0x0001 (1 byte) ✅
  - 0x0002 (2 bytes) ✅
  - 0x0004 (4 bytes) ✅
  - 0x0008 (8 bytes) ✅
  - 0x0010 (16 bytes) ✅
  - 0x0020 (32 bytes) ✅
  - 0x0040 (64 bytes) ✅
  - 0x0080 (128 bytes) ✅
  - 0x0100 (256 bytes) ✅
  - 0x0200 (512 bytes) ✅
  - 0x0400 (1024 bytes) ✅
  - 0x0800 (2048 bytes) ✅
  - 0x1000 (4096 bytes = 4KB) ✅

Result: Address is aligned to 4KB and all smaller powers of 2
```

**Example 2: Address aligned to 64KB**
```
start = 0x10000 (65536 decimal, binary: 0001 0000 0000 0000 0000)
start - 1 = 0x0FFFF (65535 decimal, binary: 0000 1111 1111 1111 1111)
start ^ (start - 1) = 0x1FFFF (binary: 0001 1111 1111 1111 1111)

This mask includes:
  - All sizes up to 32KB ✅
  - 0x10000 (65536 bytes = 64KB) ✅

Result: Address is aligned to 64KB and all smaller powers of 2
```

**Example 3: Misaligned address**
```
start = 0x1234 (4660 decimal, binary: 0001 0010 0011 0100)
start - 1 = 0x1233 (4659 decimal, binary: 0001 0010 0011 0011)
start ^ (start - 1) = 0x0007 (binary: 0000 0000 0000 0111)

This mask includes:
  - 0x0001 (1 byte) ✅
  - 0x0002 (2 bytes) ✅
  - 0x0004 (4 bytes) ✅
  - 0x0008 (8 bytes) ❌ (8 doesn't divide 0x1234)
  - 0x0010 (16 bytes) ❌
  - 0x0020 (32 bytes) ❌
  - ... all larger sizes ❌

Result: Address is ONLY aligned to 1, 2, and 4 bytes
         NOT aligned to 4KB (0x1000) or larger
```

## Alignment Requirements for GPU Chunks

### Chunk Size Alignment Rules

**Rule**: A chunk of size `S` must start at an address that is divisible by `S`.

**Examples**:

| Chunk Size | Alignment Requirement | Example Aligned Address | Example Misaligned Address |
|------------|----------------------|------------------------|---------------------------|
| 4KB (0x1000) | Address % 0x1000 == 0 | 0x1000, 0x2000, 0x3000 | 0x1001, 0x2001 |
| 64KB (0x10000) | Address % 0x10000 == 0 | 0x10000, 0x20000, 0x30000 | 0x10001, 0x20001 |
| 128KB (0x20000) | Address % 0x20000 == 0 | 0x20000, 0x40000, 0x60000 | 0x20001, 0x40001 |
| 2MB (0x200000) | Address % 0x200000 == 0 | 0x200000, 0x400000 | 0x200001, 0x400001 |

### Why Larger Chunks Require Stricter Alignment

**Larger chunks require stricter alignment** because:
- A 64KB chunk must be aligned to 64KB boundaries
- A 128KB chunk must be aligned to 128KB boundaries
- A 2MB chunk must be aligned to 2MB boundaries

**Mathematical reason**:
- If an address is aligned to 2MB, it's automatically aligned to all smaller sizes
- But if aligned only to 4KB, it's NOT aligned to 64KB, 128KB, or 2MB

## Real-World Examples

### Example 1: Perfect 2MB Alignment

```
VA Block Start: 0x2000000 (32MB, 2MB aligned)
VA Block End:   0x201FFFFF (32MB + 2MB - 1)
Fault Address:  0x2000000

Alignment Check:
  0x2000000 % 0x200000 (2MB) = 0 ✅ ALIGNED

Result: Can allocate 2MB chunk starting at 0x2000000
```

### Example 2: 64KB Alignment, Not 128KB

```
VA Block Start: 0x10000 (64KB aligned)
VA Block End:   0x1FFFF (64KB + 64KB - 1)
Fault Address:  0x10000

Alignment Check:
  0x10000 % 0x10000 (64KB) = 0 ✅ ALIGNED
  0x10000 % 0x20000 (128KB) = 0x10000 ≠ 0 ❌ NOT ALIGNED

Result: Can allocate 64KB chunk, NOT 128KB chunk
```

### Example 3: Only 4KB Alignment

```
VA Block Start: 0x1234000 (misaligned to larger sizes)
VA Block End:   0x1235FFFF
Fault Address:  0x1234123

Alignment Check:
  0x1234123 % 0x1000 (4KB) = 0x123 ≠ 0 ❌ NOT ALIGNED
  0x1234123 % 0x10000 (64KB) = 0x4123 ≠ 0 ❌ NOT ALIGNED

Alignment Fix:
  aligned_start = UVM_ALIGN_DOWN(0x1234123, 0x1000) = 0x1234000
  aligned_start % 0x1000 = 0 ✅ NOW ALIGNED

Result: Must use 4KB chunk (smallest size)
```

### Example 4: Mixed Chunk Sizes in One VA Block

```
VA Block: [0x1000000, 0x101FFFFF] (2MB block)

Page 0 (0x1000000):
  Alignment: 0x1000000 % 0x200000 = 0 ✅ 2MB aligned
  Chunk Size: 2MB (if entire block fits)

Page 512 (0x10020000):
  Alignment: 0x10020000 % 0x20000 = 0 ✅ 128KB aligned
  Chunk Size: 128KB (if remaining size >= 128KB)

Page 1024 (0x10040000):
  Alignment: 0x10040000 % 0x10000 = 0 ✅ 64KB aligned
  Chunk Size: 64KB (if remaining size >= 64KB)

Page 1536 (0x10060000):
  Alignment: 0x10060000 % 0x1000 = 0 ✅ 4KB aligned
  Chunk Size: 4KB (fallback)
```

## Alignment Calculation in Code

### Complete Algorithm

```c
// From uvm_va_block.c:1183-1213
static uvm_chunk_size_t block_gpu_chunk_size(uvm_va_block_t *block, 
                                              uvm_gpu_t *gpu, 
                                              uvm_page_index_t start_page_index)
{
    // Step 1: Get GPU-supported chunk sizes
    uvm_chunk_sizes_mask_t chunk_sizes = gpu->parent->mmu_user_chunk_sizes;
    // Example: PAGE_SIZE | 64KB | 128KB | 2MB
    
    // Step 2: Calculate start address
    NvU64 start = uvm_va_block_cpu_page_address(block, start_page_index);
    // Example: 0x10001234
    
    // Step 3: Calculate alignment mask
    // This finds all power-of-2 sizes that divide the address
    start_alignments = start ^ (start - 1);
    // Example: 0x10001234 → 0x00001111 (aligned to 1, 2, 4, 8, 16 bytes)
    
    // Step 4: Calculate size constraints
    NvU64 size = block->end - start + 1;
    pow2_leq_size = rounddown_pow_of_two(size);
    pow2_leq_size |= pow2_leq_size - 1;
    // Example: size=0x20000 → pow2_leq_size includes all sizes <= 128KB
    
    // Step 5: Intersect all constraints
    allowed_sizes = chunk_sizes & start_alignments & pow2_leq_size;
    // Only sizes that are:
    //   - Supported by GPU
    //   - Aligned to start address
    //   - Fit within remaining size
    
    // Step 6: Select largest
    return uvm_chunk_find_last_size(allowed_sizes);
    // Returns largest size that meets all constraints
}
```

## Visual Representation

### Alignment Boundaries

```
Memory Address Space:
┌─────────────────────────────────────────────────────────┐
│ 0x00000000                                              │
│                                                         │
│ 4KB boundaries:  ────┼────┼────┼────┼────┼────┼────   │
│                     0x1000 0x2000 0x3000 0x4000         │
│                                                         │
│ 64KB boundaries: ────────────┼───────────┼───────────   │
│                             0x10000     0x20000         │
│                                                         │
│ 128KB boundaries: ───────────────────┼───────────────── │
│                                     0x20000              │
│                                                         │
│ 2MB boundaries:  ────────────────────────────────────┼── │
│                                                  0x200000│
└─────────────────────────────────────────────────────────┘
```

### Example: Misaligned Address

```
Address: 0x1234
         │
         ▼
┌────────┼────────────────────────────────────────────┐
│        │                                          │
│  4KB   │  4KB   │  4KB   │  4KB   │  4KB   │    │
│        │        │        │        │        │    │
│ 0x1000 │ 0x2000 │ 0x3000 │ 0x4000 │ 0x5000 │    │
│        │        │        │        │        │    │
│        └────────┴────────┴────────┴────────┴─── │
│         ^                                          │
│         │                                          │
│    Address 0x1234 is NOT aligned to 4KB          │
│    Must round down to 0x1000 or use smaller size │
└────────────────────────────────────────────────────┘
```

### Example: Aligned Address

```
Address: 0x20000 (128KB aligned)
         │
         ▼
┌────────┼────────────────────────────────────────────┐
│        │                                          │
│  128KB │  128KB │  128KB │  128KB │  128KB │    │
│        │        │        │        │        │    │
│ 0x20000│ 0x40000│ 0x60000│ 0x80000│ 0xA0000│    │
│        │        │        │        │        │    │
│        └────────┴────────┴────────┴────────┴─── │
│         ^                                          │
│         │                                          │
│    Address 0x20000 IS aligned to 128KB            │
│    Can use 128KB chunk (or smaller)                │
└────────────────────────────────────────────────────┘
```

## Common Alignment Scenarios

### Scenario 1: Page Fault at 4KB Boundary

```
Fault Address: 0x1000
Alignment: ✅ 4KB aligned
           ✅ 64KB aligned (0x1000 % 0x10000 = 0x1000 ≠ 0, wait...)

Actually:
  0x1000 % 0x10000 = 0x1000 ≠ 0 ❌ NOT 64KB aligned

Chunk Size Selection:
  - 4KB: ✅ Aligned, fits
  - 64KB: ❌ Not aligned
  - 128KB: ❌ Not aligned
  - 2MB: ❌ Not aligned

Result: Use 4KB chunk
```

### Scenario 2: Page Fault at 64KB Boundary

```
Fault Address: 0x10000
Alignment: ✅ 4KB aligned (0x10000 % 0x1000 = 0)
           ✅ 64KB aligned (0x10000 % 0x10000 = 0)
           ❌ 128KB aligned (0x10000 % 0x20000 = 0x10000 ≠ 0)

Chunk Size Selection:
  - 4KB: ✅ Aligned, fits
  - 64KB: ✅ Aligned, fits
  - 128KB: ❌ Not aligned
  - 2MB: ❌ Not aligned

Result: Use 64KB chunk (largest that fits)
```

### Scenario 3: Page Fault at 128KB Boundary

```
Fault Address: 0x20000
Alignment: ✅ 4KB aligned
           ✅ 64KB aligned
           ✅ 128KB aligned (0x20000 % 0x20000 = 0)
           ❌ 2MB aligned (0x20000 % 0x200000 = 0x20000 ≠ 0)

Chunk Size Selection:
  - 4KB: ✅ Aligned, fits
  - 64KB: ✅ Aligned, fits
  - 128KB: ✅ Aligned, fits
  - 2MB: ❌ Not aligned

Result: Use 128KB chunk (largest that fits)
```

## Alignment and Performance

### Why Alignment Matters for Performance

1. **Fewer Allocations**: Better alignment → larger chunks → fewer allocations
2. **Better Cache Behavior**: Aligned chunks improve cache line utilization
3. **Hardware Efficiency**: Aligned accesses are faster on GPUs
4. **TLB Efficiency**: Fewer page table entries for larger aligned chunks

### Performance Impact

```
Perfect Alignment (2MB):
  → 1 allocation for entire VA block
  → Optimal performance

Good Alignment (128KB):
  → ~16 allocations for 2MB VA block
  → Good performance

Poor Alignment (4KB only):
  → ~512 allocations for 2MB VA block
  → Suboptimal performance
```

## Summary

### Key Concepts

1. **Alignment**: Address divisible by chunk size
2. **Stricter for Larger Sizes**: 2MB requires 2MB alignment, 64KB requires 64KB alignment
3. **Detection**: `start ^ (start - 1)` finds all aligned sizes
4. **Selection**: Choose largest size that is aligned and fits
5. **Performance**: Better alignment → larger chunks → better performance

### Formula

**Address `addr` is aligned to size `size` if:**
```
addr % size == 0
```

**Or using bitwise operations:**
```
(addr & (size - 1)) == 0
```

### Code Reference

- **Alignment detection**: `uvm_va_block.c:1197` (`start ^ (start - 1)`)
- **Alignment macros**: `uvm_common.h:208-217` (`UVM_ALIGN_UP`, `UVM_ALIGN_DOWN`)
- **Chunk size selection**: `uvm_va_block.c:1183-1213` (`block_gpu_chunk_size`)
