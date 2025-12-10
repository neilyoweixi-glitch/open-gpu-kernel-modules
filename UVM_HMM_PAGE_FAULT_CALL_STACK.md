# HMM Page Fault Invocation - Function Call Stacks

## Overview

HMM (Heterogeneous Memory Management) page faults in the UVM driver are invoked through two main paths:
1. **CPU Faults**: When CPU accesses GPU-resident memory (device private pages)
2. **GPU Faults**: When GPU accesses CPU-resident memory

Both paths use Linux kernel's HMM infrastructure (`migrate_vma`, `hmm_range_fault`) to coordinate memory migration.

---

## Path 1: CPU Fault on Device Private Page

### Complete Call Stack

```
Linux Kernel MMU Fault Handler
  ↓
handle_mm_fault()
  ↓
do_fault()
  ↓
do_swap_page() / do_wp_page() / do_anonymous_page()
  ↓
migrate_to_ram() callback (for ZONE_DEVICE private pages)
  ↓
[UVM Entry Point]
devmem_fault_entry()                    (uvm_pmm_gpu.c:3173)
  ↓
devmem_fault()                          (uvm_pmm_gpu.c:3163)
  ↓
uvm_va_space_cpu_fault_hmm()           (uvm_va_space.c:2747)
  ↓
uvm_va_space_cpu_fault()               (uvm_va_space.c:2531)
  │
  ├─> Acquire locks (pm lock, va_space read lock, mmap_lock)
  ├─> Allocate service_context
  │
  └─> Loop (retry on NV_WARN_MORE_PROCESSING_REQUIRED):
      │
      ├─> [HMM Path]
      │   uvm_hmm_va_block_find_create()    (uvm_hmm.c:689)
      │   │
      │   ├─> find_vma()                    (Linux kernel)
      │   ├─> hmm_va_block_find_create()    (uvm_hmm.c:601)
      │   │   │
      │   │   ├─> uvm_range_tree_find()     (Find existing block)
      │   │   ├─> uvm_va_block_create()     (Create new block if needed)
      │   │   ├─> hmm_va_block_init()       (uvm_hmm.c:589)
      │   │   └─> mmu_interval_notifier_insert() (Register with Linux MMU notifier)
      │   │
      │   └─> uvm_hmm_migrate_begin()       (uvm_hmm.c:728)
      │       → Acquire migrate_lock
      │
      └─> uvm_va_block_cpu_fault()          (uvm_va_block.c:12983)
          │
          ├─> block_cpu_fault_locked()      (uvm_va_block.c:12783)
          │   │
          │   ├─> uvm_perf_event_notify_cpu_fault()
          │   ├─> uvm_va_block_check_logical_permissions()
          │   ├─> uvm_perf_thrashing_get_hint()
          │   ├─> uvm_va_block_select_residency()
          │   │
          │   └─> uvm_va_block_service_locked()  (uvm_va_block.c:12422)
          │       │
          │       ├─> uvm_va_block_get_prefetch_hint()
          │       │
          │       └─> [HMM Block Check]
          │           if (uvm_va_block_is_hmm(va_block)):
          │               uvm_hmm_va_block_service_locked()  (uvm_hmm.c:3009)
          │           else:
          │               uvm_va_block_service_copy()
          │
          └─> uvm_hmm_migrate_finish()      (uvm_hmm.c:741)
              → Release migrate_lock
```

### Detailed Function Descriptions

#### Entry Point: `devmem_fault_entry()`

**Location**: `kernel-open/nvidia-uvm/uvm_pmm_gpu.c:3173-3176`

**Code**:
```c
static vm_fault_t devmem_fault_entry(struct vm_fault *vmf)
{
    UVM_ENTRY_RET(devmem_fault(vmf));
}
```

**Registered As**: `migrate_to_ram` callback in `uvm_pmm_devmem_ops` (`uvm_pmm_gpu.c:3178-3182`)

**When Called**: Linux kernel calls this when CPU faults on a ZONE_DEVICE private page

**Evidence**: `uvm_pmm_gpu.c:3178-3182` - Callback registration

---

#### `devmem_fault()`

**Location**: `kernel-open/nvidia-uvm/uvm_pmm_gpu.c:3163-3171`

**Code**:
```c
static vm_fault_t devmem_fault(struct vm_fault *vmf)
{
    uvm_va_space_t *va_space = uvm_pmm_devmem_page_to_va_space(vmf->page);

    if (!va_space)
        return VM_FAULT_SIGBUS;

    return uvm_va_space_cpu_fault_hmm(va_space, vmf);
}
```

**What It Does**:
- Extracts `va_space` from device private page
- Calls HMM CPU fault handler

**Evidence**: `uvm_pmm_gpu.c:3163-3171`

---

#### `uvm_va_space_cpu_fault_hmm()`

**Location**: `kernel-open/nvidia-uvm/uvm_va_space.c:2747-2750`

**Code**:
```c
vm_fault_t uvm_va_space_cpu_fault_hmm(uvm_va_space_t *va_space, struct vm_fault *vmf)
{
    return uvm_va_space_cpu_fault(va_space, vmf, true);  // is_hmm = true
}
```

**Evidence**: `uvm_va_space.c:2747-2750`

---

#### `uvm_va_space_cpu_fault()`

**Location**: `kernel-open/nvidia-uvm/uvm_va_space.c:2531-2739`

**Key Code Sections**:

```c
static vm_fault_t uvm_va_space_cpu_fault(uvm_va_space_t *va_space, struct vm_fault *vmf, bool is_hmm)
{
    // ... lock acquisition ...
    
    do {
        if (is_hmm) {
            if (va_space->va_space_mm.mm == vma->vm_mm) {
                // Find or create HMM VA block
                status = uvm_hmm_va_block_find_create(va_space,
                                                      fault_addr,
                                                      &service_context->block_context->hmm.vma,
                                                      &va_block);
                
                // Begin migration
                status = uvm_hmm_migrate_begin(va_block);
                
                service_context->cpu_fault.vmf = vmf;
            }
            else {
                // Remote MM (ptrace, etc.)
                status = uvm_hmm_remote_cpu_fault(vmf);
                break;
            }
        }
        
        // Process fault
        status = uvm_va_block_cpu_fault(va_block, fault_addr, is_write, service_context);
        
        if (is_hmm)
            uvm_hmm_migrate_finish(va_block);
    } while (status == NV_WARN_MORE_PROCESSING_REQUIRED);
}
```

**Evidence**: `uvm_va_space.c:2646-2689` - HMM path handling

---

#### `uvm_hmm_va_block_find_create()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c:689-695`

**Code**:
```c
NV_STATUS uvm_hmm_va_block_find_create(uvm_va_space_t *va_space,
                                       NvU64 addr,
                                       struct vm_area_struct **vma,
                                       uvm_va_block_t **va_block_ptr)
{
    return hmm_va_block_find_create(va_space, addr, false, vma, va_block_ptr);
}
```

**What It Does**:
- Finds existing HMM VA block or creates new one
- Registers MMU interval notifier with Linux kernel
- Returns VMA and VA block

**Evidence**: `uvm_hmm.c:689-695`, `uvm_hmm.c:601-687` (implementation)

---

#### `uvm_va_block_cpu_fault()`

**Location**: `kernel-open/nvidia-uvm/uvm_va_block.c:12983` (wrapper)

**Calls**: `block_cpu_fault_locked()` (`uvm_va_block.c:12783`)

**Key Steps**:
1. Check permissions
2. Get thrashing hints
3. Select residency
4. Call `uvm_va_block_service_locked()`

**Evidence**: `uvm_va_block.c:12783-12882`

---

#### `uvm_hmm_va_block_service_locked()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c:3009-3147`

**For CPU Faults** (destination is CPU):

```c
NV_STATUS uvm_hmm_va_block_service_locked(...)
{
    // If destination is CPU
    if (UVM_ID_IS_CPU(new_residency)) {
        return hmm_block_cpu_fault_locked(processor_id, va_block, va_block_retry, service_context);
    }
    
    // ... GPU fault path ...
}
```

**Evidence**: `uvm_hmm.c:3035-3039` - CPU fault path

---

#### `hmm_block_cpu_fault_locked()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c:2688-2800+`

**Key Steps**:

```c
static NV_STATUS hmm_block_cpu_fault_locked(...)
{
    // Setup migrate_vma arguments
    args->vma = vma;
    args->start = ...;
    args->end = ...;
    args->flags = MIGRATE_VMA_SELECT_DEVICE_PRIVATE | MIGRATE_VMA_SELECT_SYSTEM;
    
    // Setup migration
    ret = migrate_vma_setup_locked(args, va_block);
    
    // Allocate and copy pages
    status = uvm_hmm_devmem_fault_alloc_and_copy(&fault_context);
    
    // Commit migration
    migrate_vma_pages(args);
    
    // Finalize
    status = uvm_hmm_devmem_fault_finalize_and_map(&fault_context);
    migrate_vma_finalize(args);
}
```

**Evidence**: `uvm_hmm.c:2688-2800+` (function implementation)

---

## Path 2: GPU Fault on CPU Memory (HMM)

### Complete Call Stack

```
GPU Hardware
  ↓
GPU MMU Page Fault
  ↓
GPU Interrupt (ISR)
  ↓
uvm_parent_gpu_replayable_faults_isr() / uvm_parent_gpu_non_replayable_faults_isr()
  ↓
[Bottom Half - Workqueue]
uvm_parent_gpu_service_replayable_faults() / uvm_parent_gpu_service_non_replayable_faults()
  ↓
service_fault_batch()                    (uvm_gpu_replayable_faults.c)
  ↓
service_fault_batch_dispatch()          (uvm_gpu_replayable_faults.c:2168)
  ↓
service_fault_batch_block()             (uvm_gpu_replayable_faults.c:1606)
  │
  ├─> [HMM Path Check]
  │   if (mm exists):
  │       status = uvm_hmm_va_block_find_create(va_space,
  │                                             fault_address,
  │                                             &va_block_context->hmm.vma,
  │                                             &va_block);
  │
  └─> uvm_va_block_service_locked()     (uvm_va_block.c:12422)
      │
      ├─> uvm_va_block_get_prefetch_hint()
      │
      └─> [HMM Block Check]
          if (uvm_va_block_is_hmm(va_block)):
              uvm_hmm_va_block_service_locked()  (uvm_hmm.c:3009)
          else:
              uvm_va_block_service_copy()
```

### Detailed Function Descriptions

#### Entry Point: GPU ISR

**Location**: `kernel-open/nvidia-uvm/uvm_gpu_isr.c`

**Replayable Faults**:
- Top-half: `uvm_parent_gpu_replayable_faults_isr()`
- Bottom-half: `uvm_parent_gpu_service_replayable_faults()`

**Non-Replayable Faults**:
- Top-half: `uvm_parent_gpu_non_replayable_faults_isr()`
- Bottom-half: `uvm_parent_gpu_service_non_replayable_faults()`

**Evidence**: `uvm_gpu_isr.c` - ISR implementations

---

#### `service_fault_batch_dispatch()`

**Location**: `kernel-open/nvidia-uvm/uvm_gpu_replayable_faults.c:2168`

**Key Code**:
```c
// Check if HMM path
if (mm)
    status = uvm_hmm_va_block_find_create(va_space,
                                         fault_address,
                                         &va_block_context->hmm.vma,
                                         &va_block);
else
    status = uvm_va_block_find_create_managed(...);

if (status == NV_OK)
    status = service_fault_batch_block(gpu, va_block, batch_context, ...);
```

**Evidence**: `uvm_gpu_replayable_faults.c:1977-1984` - HMM block find/create

---

#### `uvm_hmm_va_block_service_locked()` (GPU Fault Path)

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c:3009-3147`

**For GPU Faults** (destination is GPU):

```c
NV_STATUS uvm_hmm_va_block_service_locked(...)
{
    // If destination is CPU, handle CPU fault
    if (UVM_ID_IS_CPU(new_residency)) {
        return hmm_block_cpu_fault_locked(...);
    }
    
    // GPU fault path:
    // 1. Pre-allocate GPU chunks
    status = uvm_va_block_populate_pages_gpu(va_block, va_block_retry, new_residency, region, new_residency_mask);
    
    // 2. Setup migrate_vma
    args->vma = vma;
    args->start = ...;
    args->end = ...;
    args->flags = MIGRATE_VMA_SELECT_DEVICE_PRIVATE | MIGRATE_VMA_SELECT_SYSTEM;
    
    // 3. Setup migration
    ret = migrate_vma_setup_locked(args, va_block);
    
    // 4. Allocate GPU pages and copy data
    status = uvm_hmm_gpu_fault_alloc_and_copy(&uvm_hmm_gpu_fault_event);
    
    // 5. Commit migration
    migrate_vma_pages(args);
    
    // 6. Finalize and map
    status = uvm_hmm_gpu_fault_finalize_and_map(&uvm_hmm_gpu_fault_event);
    
    // 7. Cleanup
    migrate_vma_finalize(args);
}
```

**Evidence**: `uvm_hmm.c:3085-3141` - GPU fault migration path

---

## Path 3: Remote CPU Fault (Remote MM)

### Call Stack

```
Linux Kernel (Remote Process)
  ↓
handle_mm_fault() (for different mm_struct)
  ↓
migrate_to_ram() callback
  ↓
devmem_fault_entry()                    (uvm_pmm_gpu.c:3173)
  ↓
devmem_fault()                          (uvm_pmm_gpu.c:3163)
  ↓
uvm_va_space_cpu_fault_hmm()           (uvm_va_space.c:2747)
  ↓
uvm_va_space_cpu_fault()               (uvm_va_space.c:2531)
  │
  └─> [Remote MM Path]
      if (is_hmm && va_space->va_space_mm.mm != vma->vm_mm):
          uvm_hmm_remote_cpu_fault(vmf)  (uvm_hmm.c:3647)
          │
          ├─> migrate_vma_setup()        (Linux kernel)
          ├─> alloc_page()                (Allocate CPU page)
          ├─> hmm_copy_devmem_page()      (Copy GPU → CPU)
          ├─> migrate_vma_pages()         (Linux kernel)
          └─> migrate_vma_finalize()       (Linux kernel)
```

### `uvm_hmm_remote_cpu_fault()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c:3647-3697`

**Code**:
```c
NV_STATUS uvm_hmm_remote_cpu_fault(struct vm_fault *vmf)
{
    // Setup migrate_vma for single page
    args.vma = vmf->vma;
    args.start = vmf->address;
    args.end = args.start + PAGE_SIZE;
    args.flags = MIGRATE_VMA_SELECT_DEVICE_PRIVATE;
    
    // Setup migration
    ret = migrate_vma_setup(&args);
    
    // Allocate CPU page
    if (src_pfn & MIGRATE_PFN_MIGRATE) {
        dst_page = alloc_page(GFP_HIGHUSER_MOVABLE);
        dst_pfn = migrate_pfn(page_to_pfn(dst_page));
        
        // Copy GPU page to CPU page
        status = hmm_copy_devmem_page(dst_page, src_page);
    }
    
    // Commit migration
    migrate_vma_pages(&args);
    migrate_vma_finalize(&args);
}
```

**When Used**: CPU fault from different process (ptrace, access_process_vm, etc.)

**Evidence**: `uvm_hmm.c:3647-3697`

---

## Key Linux Kernel Integration Points

### 1. `migrate_to_ram` Callback

**Registration**: `uvm_pmm_devmem_ops.migrate_to_ram = devmem_fault_entry`

**Location**: `kernel-open/nvidia-uvm/uvm_pmm_gpu.c:3178-3182`

**When Called**: Linux kernel MMU fault handler encounters ZONE_DEVICE private PTE

**Purpose**: Migrate device private page to system memory

**Evidence**: `uvm_pmm_gpu.c:3178-3182`

---

### 2. `migrate_vma_setup()`

**Location**: Linux kernel (`include/linux/migrate.h`)

**Purpose**: Setup migration for VMA range
- Locks pages
- Isolates pages for migration
- Returns source/destination PFN arrays

**Called From**:
- `hmm_block_cpu_fault_locked()` (`uvm_hmm.c:2720+`)
- `uvm_hmm_va_block_service_locked()` (`uvm_hmm.c:3111`)
- `uvm_hmm_remote_cpu_fault()` (`uvm_hmm.c:3667`)

**Evidence**: `uvm_hmm.c:556` (`migrate_vma_setup_locked()` wrapper)

---

### 3. `migrate_vma_pages()`

**Location**: Linux kernel

**Purpose**: Commit migration
- Copies page data
- Updates page references
- Updates page tables

**Called From**:
- `hmm_block_cpu_fault_locked()` (`uvm_hmm.c:2770+`)
- `uvm_hmm_va_block_service_locked()` (`uvm_hmm.c:3137`)

**Evidence**: `uvm_hmm.c:2770`, `uvm_hmm.c:3137`

---

### 4. `migrate_vma_finalize()`

**Location**: Linux kernel

**Purpose**: Cleanup migration
- Unlocks pages
- Releases migration resources

**Called From**:
- `hmm_block_cpu_fault_locked()` (`uvm_hmm.c:2775+`)
- `uvm_hmm_va_block_service_locked()` (`uvm_hmm.c:3141`)

**Evidence**: `uvm_hmm.c:2775`, `uvm_hmm.c:3141`

---

### 5. MMU Interval Notifier

**Registration**: `mmu_interval_notifier_insert()` (`uvm_hmm.c:661`)

**Purpose**: Register VA block with Linux MMU notifier system
- Receives invalidation callbacks
- Coordinates with Linux page table updates

**Evidence**: `uvm_hmm.c:661-665` - Notifier insertion

---

## HMM-Specific Functions

### `hmm_block_cpu_fault_locked()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c:2688-2800+`

**Purpose**: Handle CPU fault for HMM blocks

**Key Operations**:
1. Setup `migrate_vma` arguments
2. Call `migrate_vma_setup_locked()`
3. Allocate CPU pages
4. Copy data from GPU to CPU
5. Call `migrate_vma_pages()`
6. Finalize migration

**Evidence**: `uvm_hmm.c:2688-2800+`

---

### `uvm_hmm_gpu_fault_alloc_and_copy()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c` (referenced in `uvm_hmm.c:3114`)

**Purpose**: Allocate GPU pages and copy data from CPU/GPU

**Key Operations**:
1. Pre-allocated GPU chunks (from `uvm_va_block_populate_pages_gpu()`)
2. Map source pages for DMA
3. Copy data via DMA
4. Fill destination PFN array

**Evidence**: `uvm_hmm.c:3114` - Function call

---

### `uvm_hmm_gpu_fault_finalize_and_map()`

**Location**: `kernel-open/nvidia-uvm/uvm_hmm.c` (referenced in `uvm_hmm.c:3138`)

**Purpose**: Finalize GPU fault migration and map pages

**Key Operations**:
1. Update VA block residency
2. Map GPU pages in GPU page tables
3. Update CPU page tables (via `migrate_vma_pages()`)

**Evidence**: `uvm_hmm.c:3138` - Function call

---

## Locking Order

### Locks Acquired (in order)

1. **Power Management Lock** (`g_uvm_global.pm.lock`) - Read
2. **VA Space Lock** (`va_space->lock`) - Read
3. **MMAP Lock** (`vma->vm_mm->mmap_lock`) - Read (held by Linux kernel)
4. **VA Block Lock** (`va_block->lock`) - Mutex
5. **Migrate Lock** (`va_block->hmm.migrate_lock`) - Mutex (HMM only)

### Lock Release Order

Reverse of acquisition order

**Evidence**: `uvm_va_space.c:2556-2591` (lock acquisition), `uvm_hmm.c:728-743` (migrate lock)

---

## Key Differences: HMM vs. Managed Path

### HMM Path

- Uses `migrate_vma_*()` APIs
- Coordinates with Linux MMU notifier
- Handles device private pages
- Uses `hmm_range_fault()` for some operations
- Requires `mmap_lock` to be held

### Managed Path

- Uses UVM's own migration APIs
- Direct GPU-to-GPU or GPU-to-CPU copies
- No Linux MMU notifier coordination
- Simpler locking model

**Evidence**: `uvm_va_block.c:12452-12462` - HMM vs. managed path check

---

## Summary Call Stacks

### CPU Fault (HMM)

```
Linux Kernel: handle_mm_fault()
  → migrate_to_ram callback
    → devmem_fault_entry()
      → devmem_fault()
        → uvm_va_space_cpu_fault_hmm()
          → uvm_va_space_cpu_fault(is_hmm=true)
            → uvm_hmm_va_block_find_create()
            → uvm_hmm_migrate_begin()
            → uvm_va_block_cpu_fault()
              → block_cpu_fault_locked()
                → uvm_va_block_service_locked()
                  → uvm_hmm_va_block_service_locked()
                    → hmm_block_cpu_fault_locked()
                      → migrate_vma_setup_locked()
                      → uvm_hmm_devmem_fault_alloc_and_copy()
                      → migrate_vma_pages()
                      → uvm_hmm_devmem_fault_finalize_and_map()
                      → migrate_vma_finalize()
            → uvm_hmm_migrate_finish()
```

### GPU Fault (HMM)

```
GPU Hardware → ISR
  → uvm_parent_gpu_service_replayable_faults()
    → service_fault_batch()
      → service_fault_batch_dispatch()
        → uvm_hmm_va_block_find_create()
        → service_fault_batch_block()
          → uvm_va_block_service_locked()
            → uvm_hmm_va_block_service_locked()
              → uvm_va_block_populate_pages_gpu()  (Pre-allocate)
              → migrate_vma_setup_locked()
              → uvm_hmm_gpu_fault_alloc_and_copy()
              → migrate_vma_pages()
              → uvm_hmm_gpu_fault_finalize_and_map()
              → migrate_vma_finalize()
```

### Remote CPU Fault

```
Linux Kernel (Remote MM): handle_mm_fault()
  → migrate_to_ram callback
    → devmem_fault_entry()
      → devmem_fault()
        → uvm_va_space_cpu_fault_hmm()
          → uvm_va_space_cpu_fault(is_hmm=true)
            → uvm_hmm_remote_cpu_fault()
              → migrate_vma_setup()
              → alloc_page()
              → hmm_copy_devmem_page()
              → migrate_vma_pages()
              → migrate_vma_finalize()
```

---

## Code References

### Entry Points

- **CPU Fault**: `uvm_pmm_gpu.c:3163` (`devmem_fault`)
- **GPU Fault**: `uvm_gpu_replayable_faults.c:1978` (`uvm_hmm_va_block_find_create`)
- **Remote CPU Fault**: `uvm_hmm.c:3647` (`uvm_hmm_remote_cpu_fault`)

### Core Functions

- **HMM Service**: `uvm_hmm.c:3009` (`uvm_hmm_va_block_service_locked`)
- **CPU Fault Handler**: `uvm_hmm.c:2688` (`hmm_block_cpu_fault_locked`)
- **Block Find/Create**: `uvm_hmm.c:689` (`uvm_hmm_va_block_find_create`)
- **Migration Begin/Finish**: `uvm_hmm.c:728` (`uvm_hmm_migrate_begin`), `uvm_hmm.c:741` (`uvm_hmm_migrate_finish`)

### Linux Kernel Integration

- **Callback Registration**: `uvm_pmm_gpu.c:3178-3182` (`uvm_pmm_devmem_ops`)
- **MMU Notifier**: `uvm_hmm.c:661` (`mmu_interval_notifier_insert`)
- **Migration APIs**: `uvm_hmm.c:556` (`migrate_vma_setup_locked`)
