# Virtual Memory Management Files - Quick Reference

## Complete File List (69 files)

### Core VASpace Files (4 files)
- `src/nvidia/src/kernel/mem_mgr/vaspace.c` (261 lines)
- `src/nvidia/inc/kernel/mem_mgr/vaspace.h` (3 lines)
- `src/nvidia/src/kernel/gpu/mem_mgr/vaspace_api.c` (796 lines)
- `src/nvidia/inc/kernel/gpu/mem_mgr/vaspace_api.h` (3 lines)

### GPU VASpace Files (2 files)
- `src/nvidia/src/kernel/mem_mgr/gpu_vaspace.c` (5,394 lines) ⭐ LARGEST
- `src/nvidia/inc/kernel/mem_mgr/gpu_vaspace.h` (3 lines)

### IO VASpace Files (2 files)
- `src/nvidia/src/kernel/mem_mgr/io_vaspace.c` (605 lines)
- `src/nvidia/inc/kernel/mem_mgr/io_vaspace.h` (3 lines)

### Fabric VASpace Files (2 files)
- `src/nvidia/src/kernel/mem_mgr/fabric_vaspace.c` (1,291 lines)
- `src/nvidia/inc/kernel/mem_mgr/fabric_vaspace.h` (3 lines)

### Virtual Memory Allocator Files (6 files)
- `src/nvidia/src/kernel/gpu/mem_mgr/virt_mem_allocator.c` (83 lines)
- `src/nvidia/inc/kernel/gpu/mem_mgr/virt_mem_allocator.h` (3 lines)
- `src/nvidia/inc/kernel/gpu/mem_mgr/virt_mem_allocator_common.h` (108 lines)
- `src/nvidia/src/kernel/gpu/mem_mgr/virt_mem_allocator_vgpu.c` (57 lines)
- `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c` (3,093 lines) ⭐ 3RD LARGEST
- `src/nvidia/src/kernel/gpu/mem_mgr/arch/hopper/virt_mem_allocator_gh100.c` (206 lines)

### Virtual Memory Manager Files (6 files)
- `src/nvidia/src/kernel/mem_mgr/virt_mem_mgr.c` (218 lines)
- `src/nvidia/inc/kernel/mem_mgr/virt_mem_mgr.h` (3 lines)
- `src/nvidia/src/kernel/mem_mgr/virt_mem_range.c` (143 lines)
- `src/nvidia/inc/kernel/mem_mgr/virt_mem_range.h` (3 lines)
- `src/nvidia/src/kernel/mem_mgr/virtual_mem.c` (1,883 lines) ⭐ 5TH LARGEST
- `src/nvidia/inc/kernel/mem_mgr/virtual_mem.h` (3 lines)

### DMA Files (1 file)
- `src/nvidia/src/kernel/gpu/mem_mgr/dma.c` (1,301 lines) ⭐ 7TH LARGEST

### MMU Library Files (13 files)
- `src/nvidia/src/libraries/mmu/mmu_walk.c` (1,591 lines) ⭐ 6TH LARGEST
- `src/nvidia/src/libraries/mmu/mmu_walk_map.c` (218 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_unmap.c` (87 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_fill.c` (379 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_info.c` (58 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_reserve.c` (242 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_migrate.c` (186 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_commit.c` (133 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_sparse.c` (118 lines)
- `src/nvidia/src/libraries/mmu/mmu_fmt.c` (162 lines)
- `src/nvidia/src/libraries/mmu/mmu_walk_private.h` (376 lines)
- `src/nvidia/inc/libraries/mmu/mmu_walk.h` (858 lines) ⭐ 10TH LARGEST
- `src/nvidia/inc/libraries/mmu/mmu_fmt.h` (237 lines)

### GMMU Files (5 files)
- `src/nvidia/src/libraries/mmu/gmmu_fmt.c` (278 lines)
- `src/nvidia/inc/libraries/mmu/gmmu_fmt.h` (696 lines)
- `src/nvidia/src/kernel/gpu/mmu/gmmu_walk.c` (1,073 lines) ⭐ 9TH LARGEST
- `src/nvidia/src/kernel/gpu/mmu/gmmu_trace.c` (562 lines)
- `src/nvidia/inc/kernel/gpu/mmu/kern_gmmu.h` (3 lines)

### MMU Kernel Files (5 files)
- `src/nvidia/src/kernel/gpu/mmu/mmu_fault_buffer.c` (194 lines)
- `src/nvidia/inc/kernel/gpu/mmu/mmu_fault_buffer.h` (3 lines)
- `src/nvidia/src/kernel/gpu/mmu/mmu_fault_buffer_ctrl.c` (217 lines)
- `src/nvidia/src/kernel/gpu/mmu/mmu_trace.c` (843 lines)
- `src/nvidia/inc/kernel/gpu/mmu/mmu_trace.h` (111 lines)

### Generated NVOC Files (22 files)

#### C Files (11 files)
- `src/nvidia/generated/g_vaspace_nvoc.c` (171 lines)
- `src/nvidia/generated/g_vaspace_api_nvoc.c` (620 lines)
- `src/nvidia/generated/g_gpu_vaspace_nvoc.c` (446 lines)
- `src/nvidia/generated/g_io_vaspace_nvoc.c` (446 lines)
- `src/nvidia/generated/g_fabric_vaspace_nvoc.c` (446 lines)
- `src/nvidia/generated/g_virt_mem_allocator_nvoc.c` (506 lines)
- `src/nvidia/generated/g_virt_mem_mgr_nvoc.c` (198 lines)
- `src/nvidia/generated/g_virt_mem_range_nvoc.c` (641 lines)
- `src/nvidia/generated/g_virtual_mem_nvoc.c` (587 lines)
- `src/nvidia/generated/g_mmu_fault_buffer_nvoc.c` (693 lines)
- `src/nvidia/generated/g_kern_gmmu_nvoc.c` (1,926 lines) ⭐ 4TH LARGEST

#### Header Files (11 files)
- `src/nvidia/generated/g_vaspace_nvoc.h` (700 lines)
- `src/nvidia/generated/g_vaspace_api_nvoc.h` (427 lines)
- `src/nvidia/generated/g_gpu_vaspace_nvoc.h` (827 lines)
- `src/nvidia/generated/g_io_vaspace_nvoc.h` (486 lines)
- `src/nvidia/generated/g_fabric_vaspace_nvoc.h` (550 lines)
- `src/nvidia/generated/g_virt_mem_allocator_nvoc.h` (672 lines)
- `src/nvidia/generated/g_virt_mem_mgr_nvoc.h` (177 lines)
- `src/nvidia/generated/g_virt_mem_range_nvoc.h` (334 lines)
- `src/nvidia/generated/g_virtual_mem_nvoc.h` (385 lines)
- `src/nvidia/generated/g_mmu_fault_buffer_nvoc.h` (447 lines)
- `src/nvidia/generated/g_kern_gmmu_nvoc.h` (3,095 lines) ⭐ 2ND LARGEST

### Common/Shared Headers (1 file)
- `src/common/sdk/nvidia/inc/mmu_fmt_types.h` (151 lines)

---

## Summary

- **Total Files**: 69
- **C Source Files**: 40 (28,352 lines)
- **Header Files**: 29 (10,670 lines)
- **Total Lines**: 39,022
- **Code Lines**: 26,185

## Key Files by Size

1. `gpu_vaspace.c` - 5,394 lines
2. `g_kern_gmmu_nvoc.h` - 3,095 lines
3. `virt_mem_allocator_gm107.c` - 3,093 lines
4. `g_kern_gmmu_nvoc.c` - 1,926 lines
5. `virtual_mem.c` - 1,883 lines
6. `mmu_walk.c` - 1,591 lines
7. `dma.c` - 1,301 lines
8. `fabric_vaspace.c` - 1,291 lines
9. `gmmu_walk.c` - 1,073 lines
10. `mmu_walk.h` - 858 lines
