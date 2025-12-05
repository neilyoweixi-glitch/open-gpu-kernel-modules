# NVIDIA-UVM Driver File-Level Lines of Code Analysis

## Executive Summary

This document provides a comprehensive file-level analysis of the NVIDIA Unified Virtual Memory (UVM) driver implementation. UVM enables unified virtual memory between CPU and GPU, allowing seamless memory sharing and migration.

**Total Statistics:**
- **Total Files**: 256 files
- **C Source Files**: 136 files (106,995 lines)
- **Header Files**: 120 files (44,302 lines)
- **Total Lines**: 151,297 lines
- **Code Lines**: 90,087 lines (excluding comments and empty lines)

---

## Files by Location/Category

### 1. kernel-open/nvidia-uvm (Main UVM Driver)

**Purpose**: Core UVM kernel module implementation

| Type | Files | Lines | Code Lines | Avg Lines/File |
|------|-------|-------|-------------|----------------|
| C Source | 127 | 103,384 | 69,835 | 814 |
| Header | 116 | 42,687 | 16,577 | 368 |
| **Total** | **243** | **146,071** | **86,412** | **601** |

**Top 10 Largest Files:**

| Rank | File | Lines | Code Lines | Description |
|------|------|-------|-------------|-------------|
| 1 | `uvm_va_block.c` | 14,177 | 9,626 | ⭐ **LARGEST** - Virtual address block management |
| 2 | `uvm_channel.c` | 4,365 | 2,882 | GPU channel management |
| 3 | `uvm.h` | 4,259 | 231 | Main UVM header |
| 4 | `uvm_pmm_gpu.c` | 4,075 | 2,660 | GPU physical memory manager |
| 5 | `uvm_hmm.c` | 3,941 | 2,739 | Heterogeneous Memory Management |
| 6 | `uvm_gpu.c` | 3,929 | 2,765 | GPU object management |
| 7 | `uvm_gpu_replayable_faults.c` | 3,118 | 1,989 | Replayable fault handling |
| 8 | `uvm_mmu.c` | 3,051 | 2,103 | MMU operations |
| 9 | `uvm_tools.c` | 2,863 | 2,139 | Debug tools |
| 10 | `uvm_page_tree_test.c` | 2,819 | 2,097 | Page tree tests |

**Key Components:**
- Virtual address space management
- Page fault handling
- Memory migration
- GPU channel management
- Performance optimization

---

### 2. src/nvidia/src/kernel/gpu/uvm (Kernel-Side UVM Support)

**Purpose**: Kernel-side UVM integration and architecture-specific implementations

| Type | Files | Lines | Code Lines | Description |
|------|------|-------|------------|-------------|
| C Source | 4 | 1,351 | 985 | Architecture-specific UVM support |

**Files:**
- `uvm.c` (360 lines) - Base UVM kernel support
- `uvm_tu102.c` (472 lines) - Turing architecture support
- `uvm_gv100.c` (400 lines) - Volta architecture support
- `uvm_gb100.c` (119 lines) - Blackwell architecture support

---

### 3. src/nvidia/inc/kernel/gpu/uvm (UVM Headers)

**Purpose**: UVM header definitions

| Type | Files | Lines | Code Lines |
|------|-------|-------|------------|
| Header | 1 | 3 | 1 |

**Files:**
- `uvm.h` (3 lines) - UVM header

---

### 4. src/nvidia/src/kernel/gpu/mmu (UVM SW Support)

**Purpose**: UVM software layer support

| Type | Files | Lines | Code Lines |
|------|-------|-------|------------|
| C Source | 1 | 64 | 36 |

**Files:**
- `uvm_sw.c` (64 lines) - UVM software layer

---

### 5. src/nvidia/src/kernel/gpu/fifo (UVM Channel Retainer)

**Purpose**: UVM channel retention support

| Type | Files | Lines | Code Lines |
|------|-------|-------|------------|
| C Source | 1 | 151 | 88 |

**Files:**
- `uvm_channel_retainer.c` (151 lines) - Channel retention for UVM

---

### 6. src/nvidia/generated (Generated NVOC Files)

**Purpose**: Auto-generated NVOC wrapper code for UVM objects

| Type | Files | Lines | Code Lines |
|------|-------|-------|------------|
| C Source | 3 | 2,045 | 1,534 |
| Header | 3 | 1,612 | 1,031 |
| **Total** | **6** | **3,657** | **2,565** |

**Files:**
- `g_uvm_nvoc.c` (825 lines) - UVM object wrapper
- `g_uvm_nvoc.h` (854 lines) - UVM object header
- `g_uvm_sw_nvoc.c` (685 lines) - UVM SW wrapper
- `g_uvm_sw_nvoc.h` (399 lines) - UVM SW header
- `g_uvm_channel_retainer_nvoc.c` (535 lines) - Channel retainer wrapper
- `g_uvm_channel_retainer_nvoc.h` (323 lines) - Channel retainer header

---

## Files by Functionality

### Virtual Address Management (10 files, 25,449 lines, 15,814 code)

**Purpose**: Core virtual address space and block management

**Key Files:**
- `uvm_va_block.c` (14,177 lines) - ⭐ **LARGEST FILE** - VA block operations
- `uvm_va_block.h` (2,364 lines) - VA block definitions
- `uvm_va_space.c` (2,750 lines) - VA space management
- `uvm_va_range.c` (2,335 lines) - VA range operations
- `uvm_va_range_device_p2p.c` - P2P VA range support
- `uvm_va_policy.c` - VA policy management

**Functionality:**
- Virtual address block allocation and management
- VA space creation and destruction
- VA range tracking
- Policy enforcement

---

### Fault Handling (30 files, 10,450 lines, 4,827 code)

**Purpose**: Page fault handling and fault buffer management

**Key Files:**
- `uvm_gpu_replayable_faults.c` (3,118 lines) - Replayable fault handling
- `uvm_gpu_non_replayable_faults.c` - Non-replayable fault handling
- `uvm_fault_buffer_flush_test.c` - Fault buffer flush tests
- Architecture-specific fault buffers:
  - `uvm_pascal_fault_buffer.c`
  - `uvm_volta_fault_buffer.c`
  - `uvm_turing_fault_buffer.c`
  - `uvm_ampere_fault_buffer.c`
  - `uvm_hopper_fault_buffer.h`
  - `uvm_blackwell_fault_buffer.c`
  - `uvm_ada_fault_buffer.h`

**Functionality:**
- Page fault detection and handling
- Fault buffer management
- Fault replay mechanisms
- Architecture-specific fault handling

---

### Channel/Synchronization (12 files, 9,869 lines, 5,956 code)

**Purpose**: GPU channel management and synchronization primitives

**Key Files:**
- `uvm_channel.c` (4,365 lines) - ⭐ **2ND LARGEST** - Channel management
- `uvm_channel_test.c` (1,906 lines) - Channel tests
- `uvm_push.c` - Push buffer operations
- `uvm_pushbuffer.h` - Push buffer definitions
- `uvm_gpu_semaphore.c` - GPU semaphore implementation
- `uvm_gpu_semaphore.h` - Semaphore definitions
- `uvm_user_channel.c` - User-space channel interface

**Functionality:**
- GPU channel allocation and management
- Command submission
- Synchronization primitives
- User-space channel access

---

### Architecture-Specific (24 files, 8,308 lines, 5,684 code)

**Purpose**: Architecture-specific UVM implementations

**Key Files:**
- `uvm_pascal.c`, `uvm_pascal_host.c`, `uvm_pascal_mmu.c`, `uvm_pascal_ce.c`
- `uvm_volta.c`, `uvm_volta_host.c`, `uvm_volta_mmu.c`, `uvm_volta_ce.c`
- `uvm_turing.c`, `uvm_turing_host.c`, `uvm_turing_mmu.c`
- `uvm_ampere.c`, `uvm_ampere_host.c`, `uvm_ampere_mmu.c`, `uvm_ampere_ce.c`
- `uvm_hopper.c`, `uvm_hopper_mmu.c`, `uvm_hopper_ce.c`
- `uvm_blackwell.c`, `uvm_blackwell_host.c`
- `uvm_ada.c`
- `uvm_tu102.c` (472 lines) - Turing kernel support
- `uvm_gv100.c` (400 lines) - Volta kernel support
- `uvm_gb100.c` (119 lines) - Blackwell kernel support

**Architectures Supported:**
- Pascal (GP100)
- Volta (GV100)
- Turing (TU102)
- Ampere
- Hopper
- Blackwell
- Ada

---

### MMU Operations (14 files, 8,929 lines, 3,958 code)

**Purpose**: Memory Management Unit operations

**Key Files:**
- `uvm_mmu.c` (3,051 lines) - MMU operations
- `uvm_mmu.h` - MMU definitions
- Architecture-specific MMU:
  - `uvm_pascal_mmu.c`
  - `uvm_volta_mmu.c`
  - `uvm_turing_mmu.c`
  - `uvm_ampere_mmu.c`
  - `uvm_hopper_mmu.c`

**Functionality:**
- Page table management
- TLB invalidation
- MMU format handling
- Architecture-specific MMU operations

---

### Memory Management (8 files, 8,360 lines, 5,141 code)

**Purpose**: Physical and virtual memory management

**Key Files:**
- `uvm_pmm_gpu.c` (4,075 lines) - ⭐ **4TH LARGEST** - GPU physical memory manager
- `uvm_pmm_sysmem.c` - System memory manager
- `uvm_pmm_sysmem.h` - System memory definitions
- `uvm_pmm_gpu.h` - GPU PMM definitions
- `uvm_mem.c` - Memory object management
- `uvm_mem.h` - Memory object definitions
- `uvm_rm_mem.c` - RM memory integration
- `uvm_rm_mem.h` - RM memory definitions

**Functionality:**
- Physical memory allocation
- Memory object lifecycle
- System memory management
- GPU memory management

---

### Performance (12 files, 4,435 lines, 2,692 code)

**Purpose**: Performance optimization and prefetching

**Key Files:**
- `uvm_perf_thrashing.c` (2,173 lines) - Thrashing detection
- `uvm_perf_prefetch.c` - Prefetching logic
- `uvm_perf_heuristics.c` - Performance heuristics
- `uvm_perf_heuristics.h` - Heuristics definitions
- `uvm_perf_module.c` - Performance module
- `uvm_perf_utils.c` - Performance utilities
- `uvm_perf_events.c` - Performance events

**Functionality:**
- Memory access pattern analysis
- Prefetching strategies
- Thrashing detection and mitigation
- Performance monitoring

---

### Migration (4 files, 3,058 lines, 2,004 code)

**Purpose**: Memory migration between CPU and GPU

**Key Files:**
- `uvm_migrate_pageable.c` (1,540 lines) - Pageable memory migration
- `uvm_migrate_pageable.h` - Migration definitions
- `uvm_migrate.c` - Migration operations
- `uvm_populate_pageable.c` - Pageable population

**Functionality:**
- CPU-GPU memory migration
- Pageable memory handling
- Migration policies

---

### Tests (35 files, 20,655 lines, 14,082 code)

**Purpose**: Unit tests and self-tests

**Key Files:**
- `uvm_page_tree_test.c` (2,819 lines) - Page tree tests
- `uvm_channel_test.c` (1,906 lines) - Channel tests
- `uvm_range_tree_test.c` (1,716 lines) - Range tree tests
- `uvm_tracker_test.c` - Tracker tests
- `uvm_va_block_test.c` - VA block tests
- `uvm_pmm_test.c` - PMM tests
- `uvm_ce_test.c` - Copy engine tests
- `uvm_host_test.c` - Host tests
- `uvm_lock_test.c` - Lock tests
- `uvm_gpu_semaphore_test.c` - Semaphore tests
- And many more...

**Coverage:**
- Unit tests for core components
- Integration tests
- Stress tests
- Performance tests

---

### Policy Management (5 files, 3,207 lines, 2,224 code)

**Purpose**: Memory policy and range group management

**Key Files:**
- `uvm_policy.c` - Policy implementation
- `uvm_range_group.c` - Range group management
- `uvm_range_group_tree_test.c` - Range group tests

**Functionality:**
- Memory access policies
- Range grouping
- Policy enforcement

---

### ATS (Address Translation Services) (4 files, 852 lines, 444 code)

**Purpose**: ATS support for IOMMU

**Key Files:**
- `uvm_ats.c` - ATS implementation
- `uvm_ats.h` - ATS definitions
- `uvm_ats_faults.c` - ATS fault handling
- `uvm_ats_sva.c` - Shared Virtual Addressing

**Functionality:**
- IOMMU integration
- ATS fault handling
- Shared virtual addressing

---

### Synchronization (4 files, 2,317 lines, 1,227 code)

**Purpose**: Synchronization primitives

**Key Files:**
- `uvm_tracker.c` - Tracker implementation
- `uvm_tracker.h` - Tracker definitions
- `uvm_lock.c` - Lock implementation
- `uvm_lock.h` - Lock definitions

**Functionality:**
- Dependency tracking
- Lock management
- Synchronization primitives

---

### Debug/Tools (5 files, 3,194 lines, 2,310 code)

**Purpose**: Debugging and diagnostic tools

**Key Files:**
- `uvm_tools.c` (2,863 lines) - Debug tools
- `uvm_tools.h` - Tools definitions
- `uvm_procfs.c` - Proc filesystem interface
- `uvm_procfs.h` - Procfs definitions
- `uvm_test_ioctl.h` (1,585 lines) - Test ioctl definitions

**Functionality:**
- Debug interfaces
- Proc filesystem
- Diagnostic tools
- Test interfaces

---

### Core/Common (4 files, 1,716 lines, 994 code)

**Purpose**: Core utilities and common code

**Key Files:**
- `uvm_common.c` - Common utilities
- `uvm_global.c` - Global state
- `uvm_global.h` - Global definitions
- `uvm_linux.c` - Linux-specific code
- `uvm_linux.h` - Linux definitions

**Functionality:**
- Common utilities
- Global state management
- OS-specific code

---

### API/Interface (3 files, 1,467 lines, 810 code)

**Purpose**: User-space API and interfaces

**Key Files:**
- `uvm_api.h` - API definitions
- `uvm_ioctl.h` - IOCTL definitions
- `uvm_fd_type.c` - File descriptor types

**Functionality:**
- User-space API
- IOCTL interface
- File descriptor management

---

## Top 20 Largest Files

| Rank | File | Lines | Code Lines | Category |
|------|------|-------|------------|----------|
| 1 | `uvm_va_block.c` | 14,177 | 9,626 | Virtual Address Management |
| 2 | `uvm_channel.c` | 4,365 | 2,882 | Channel/Synchronization |
| 3 | `uvm.h` | 4,259 | 231 | Core Header |
| 4 | `uvm_pmm_gpu.c` | 4,075 | 2,660 | Memory Management |
| 5 | `uvm_hmm.c` | 3,941 | 2,739 | Memory Management |
| 6 | `uvm_gpu.c` | 3,929 | 2,765 | GPU Management |
| 7 | `uvm_gpu_replayable_faults.c` | 3,118 | 1,989 | Fault Handling |
| 8 | `uvm_mmu.c` | 3,051 | 2,103 | MMU Operations |
| 9 | `uvm_tools.c` | 2,863 | 2,139 | Debug/Tools |
| 10 | `uvm_page_tree_test.c` | 2,819 | 2,097 | Tests |
| 11 | `uvm_va_space.c` | 2,750 | 1,794 | Virtual Address Management |
| 12 | `uvm_va_block.h` | 2,364 | 882 | Virtual Address Management |
| 13 | `uvm_va_range.c` | 2,335 | 1,663 | Virtual Address Management |
| 14 | `uvm_gpu_access_counters.c` | 2,248 | 1,544 | Performance |
| 15 | `uvm_perf_thrashing.c` | 2,173 | 1,385 | Performance |
| 16 | `uvm_channel_test.c` | 1,906 | 1,273 | Tests |
| 17 | `uvm_gpu.h` | 1,888 | 717 | GPU Management |
| 18 | `uvm_range_tree_test.c` | 1,716 | 1,210 | Tests |
| 19 | `uvm_test_ioctl.h` | 1,585 | 928 | Debug/Tools |
| 20 | `uvm_migrate_pageable.c` | 1,540 | 1,085 | Migration |

---

## Summary Statistics

### By File Type

| Type | Files | Total Lines | Code Lines | Avg Lines/File |
|------|-------|-------------|------------|----------------|
| C Source | 136 | 106,995 | 72,478 | 786 |
| Header | 120 | 44,302 | 17,609 | 369 |
| **Total** | **256** | **151,297** | **90,087** | **591** |

### Generated vs Non-Generated

| Category | Files | Lines | Code Lines |
|----------|-------|-------|------------|
| Generated | 6 | 3,657 | 2,565 |
| Non-Generated | 250 | 147,640 | 87,522 |

### Code Distribution by Functionality

| Functionality | Files | Lines | Code Lines | % of Total |
|---------------|-------|-------|------------|------------|
| Virtual Address Management | 10 | 25,449 | 15,814 | 16.8% |
| Tests | 35 | 20,655 | 14,082 | 15.6% |
| Fault Handling | 30 | 10,450 | 4,827 | 5.4% |
| Channel/Synchronization | 12 | 9,869 | 5,956 | 6.6% |
| MMU Operations | 14 | 8,929 | 3,958 | 4.4% |
| Architecture-Specific | 24 | 8,308 | 5,684 | 6.3% |
| Memory Management | 8 | 8,360 | 5,141 | 5.7% |
| Performance | 12 | 4,435 | 2,692 | 3.0% |
| Other | 78 | 36,268 | 19,978 | 22.2% |
| Migration | 4 | 3,058 | 2,004 | 2.2% |
| Policy Management | 5 | 3,207 | 2,224 | 2.5% |
| Debug/Tools | 5 | 3,194 | 2,310 | 2.6% |
| Synchronization | 4 | 2,317 | 1,227 | 1.4% |
| Generated Code | 4 | 2,763 | 1,942 | 2.2% |
| Core/Common | 4 | 1,716 | 994 | 1.1% |
| API/Interface | 3 | 1,467 | 810 | 0.9% |
| ATS | 4 | 852 | 444 | 0.5% |

---

## Key Architectural Components

### 1. Virtual Address Management (16.8% of code)

The largest component, handling:
- VA block lifecycle management
- VA space tracking
- VA range operations
- Policy enforcement

**Core Files:**
- `uvm_va_block.c` (14,177 lines) - Central to UVM operation
- `uvm_va_space.c` (2,750 lines) - VA space management
- `uvm_va_range.c` (2,335 lines) - Range operations

### 2. Fault Handling (5.4% of code)

Critical for page fault management:
- Replayable and non-replayable faults
- Architecture-specific fault buffers
- Fault replay mechanisms

**Core Files:**
- `uvm_gpu_replayable_faults.c` (3,118 lines)
- Architecture-specific fault buffer implementations

### 3. Channel Management (6.6% of code)

GPU command submission:
- Channel allocation and management
- Command push buffers
- Synchronization primitives

**Core Files:**
- `uvm_channel.c` (4,365 lines)
- `uvm_push.c`
- `uvm_gpu_semaphore.c`

### 4. Memory Management (5.7% of code)

Physical memory allocation:
- GPU physical memory manager
- System memory manager
- Memory object lifecycle

**Core Files:**
- `uvm_pmm_gpu.c` (4,075 lines)
- `uvm_pmm_sysmem.c`
- `uvm_mem.c`

---

## File Organization

### Directory Structure

```
kernel-open/nvidia-uvm/
├── Core UVM files (uvm.c, uvm.h, uvm_common.c)
├── Virtual Address Management (uvm_va_*.c)
├── Fault Handling (uvm_*_fault*.c)
├── Architecture-Specific (uvm_<arch>*.c)
├── MMU Operations (uvm_mmu.c, uvm_*_mmu.c)
├── Memory Management (uvm_pmm_*.c, uvm_mem.c)
├── Channel Management (uvm_channel.c, uvm_push.c)
├── Performance (uvm_perf_*.c)
├── Migration (uvm_migrate*.c)
├── Tests (uvm_*_test.c)
└── Tools (uvm_tools.c, uvm_procfs.c)

src/nvidia/src/kernel/gpu/uvm/
├── uvm.c (Base support)
└── arch/
    ├── turing/uvm_tu102.c
    ├── volta/uvm_gv100.c
    └── blackwell/uvm_gb100.c
```

---

## Conclusion

The NVIDIA-UVM driver is a substantial codebase with **256 files** totaling **151,297 lines** of code. The implementation is well-organized into distinct functional areas:

1. **Virtual Address Management** (16.8%) - Core VA block and space management
2. **Tests** (15.6%) - Comprehensive test coverage
3. **Fault Handling** (5.4%) - Page fault management
4. **Channel Management** (6.6%) - GPU command submission
5. **Memory Management** (5.7%) - Physical memory allocation
6. **Architecture Support** (6.3%) - Multi-architecture support

The largest single file is `uvm_va_block.c` with **14,177 lines**, demonstrating the complexity of virtual address block management in unified virtual memory systems.

The codebase shows:
- **Strong test coverage** (35 test files, 20,655 lines)
- **Multi-architecture support** (Pascal through Blackwell)
- **Comprehensive fault handling** (30 fault-related files)
- **Performance optimization** (12 performance-related files)
- **Well-structured organization** with clear separation of concerns

This analysis demonstrates the scale and complexity of implementing unified virtual memory between CPU and GPU systems.
