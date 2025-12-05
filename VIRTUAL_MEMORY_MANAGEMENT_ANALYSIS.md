# Virtual Memory Management Code Analysis

## Executive Summary

This document provides a comprehensive breakdown of virtual memory management code in the NVIDIA driver codebase, covering virtual addresses, buffers, physical memory, and page table manipulations. Each section includes specific code references and evidence.

---

## 1. Virtual Address Space Management

### 1.1 Virtual Address Space (VASpace) Abstraction

**Core Structure**: `OBJVASPACE` - Abstract base class for managing virtual address spaces

**Evidence**:
- **File**: `src/nvidia/generated/g_vaspace_nvoc.h:254`
  ```c
  /**
   * Abstract base class of an RM-managed virtual address space.
   */
  ```

**Key Operations**:
- **Virtual Address Allocation**: `vaspaceAlloc()`
  - **Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:302`
    ```c
    NV_STATUS (*__vaspaceAlloc__)(struct OBJVASPACE * /*this*/, NvU64, NvU64, NvU64, NvU64, NvU64, VAS_ALLOC_FLAGS, NvU64 *);
    ```
  - **Implementation**: `src/nvidia/src/kernel/mem_mgr/vaspace.c:52-157`
    - Handles VA range calculation, alignment, and allocation flags
    - Supports fixed address allocation, restricted ranges, and 32-bit pointer enforcement

- **Virtual Address Free**: `vaspaceFree()`
  - **Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:303`
    ```c
    NV_STATUS (*__vaspaceFree__)(struct OBJVASPACE * /*this*/, NvU64);
    ```

- **Virtual Address Range Queries**:
  - **Evidence**: `src/nvidia/src/kernel/mem_mgr/vaspace.c:159-169`
    ```c
    NvU64 vaspaceGetVaStart_IMPL(OBJVASPACE *pVAS) {
        return pVAS->vasStart;
    }
    
    NvU64 vaspaceGetVaLimit_IMPL(OBJVASPACE *pVAS) {
        return pVAS->vasLimit;
    }
    ```

### 1.2 Virtual Address Allocation Parameters

**Evidence**: `src/nvidia/src/kernel/mem_mgr/vaspace.c:52-157`

Key parameters handled:
- **Size and Alignment**: Applied via `vaspaceApplyDefaultAlignment()`
- **Range Restrictions**: `rangeLo` and `rangeHi` define valid VA ranges
- **Page Size Lock Mask**: Controls page size granularity
- **Allocation Flags**: 
  - `bReverse`: Force memory to grow downward
  - `bPreferSysmemPageTables`: Prefer system memory for page tables
  - `bSparse`: Sparse allocation support
  - `bPrivileged`: Kernel-level allocation

**32-bit Pointer Enforcement**:
- **Evidence**: `src/nvidia/src/kernel/mem_mgr/vaspace.c:112-124`
  ```c
  if (FLD_TEST_DRF(OS32, _ATTR2, _32BIT_POINTER, _ENABLE, pAllocInfo->pageFormat->attr2))
  {
      *pRangeHi = NV_MIN(*pRangeHi, NVBIT64(32) - 1);
  }
  ```

---

## 2. Buffer Management and Virtual Memory Mapping

### 2.1 Virtual Memory Buffer Mapping

**Core Function**: `dmaMapBuffer()` - Maps physical memory buffers to virtual addresses

**Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:2701-2865`

**Key Steps**:
1. **Calculate Virtual Address Size**:
   - **Evidence**: Lines 2781-2786
     ```c
     mapLength  = RM_ALIGN_UP(pageOffs + memdescGetSize(pMemDesc), pageSize);
     vaddr     = 0;
     compAlign = NVBIT64(comprInfo.compPageShift);
     vaAlign   = NV_MAX(pageSize, compAlign);
     vaSize    = RM_ALIGN_UP(mapLength, vaAlign);
     ```

2. **Allocate Virtual Address**:
   - **Evidence**: Lines 2830-2836
     ```c
     status = vaspaceAlloc(pVAS, vaSize, vaAlign, rangeLo, rangeHi,
                          pageSize, allocFlags, &vaddr);
     ```

3. **Update Page Tables**:
   - **Evidence**: Lines 2845-2850
     ```c
     dmaPageArrayInit(&pageArray,
         memdescGetPteArray(pSubDevMemDesc, VAS_ADDRESS_TRANSLATION(pVAS)),
         pteCount);
     flags = flagsForUpdate;
     ```

### 2.2 Buffer Unmapping

**Core Function**: `dmaUnmapBuffer()` - Unmaps virtual address mappings

**Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:2902`

**Usage Example**:
- **Evidence**: `src/nvidia/src/kernel/gpu/fifo/kernel_channel.c:3668`
  ```c
  dmaUnmapBuffer_HAL(pGpu, GPU_GET_DMA(pGpu), pVas, vAddr);
  ```

### 2.3 DMA Mapping Operations

**Core Functions**:
- `dmaAllocMap()` - Allocates and maps DMA buffers
  - **Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/dma.c:75-200`
  - Handles P2P (peer-to-peer) mappings, fabric memory, and MIG partitioning

- `dmaFreeMap()` - Frees DMA mappings
  - **Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/dma.c:217-258`

**Virtual Address Calculation**:
- **Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/dma.c:137-147`
  ```c
  virtmemGetAddressAndSize(pVirtualMemory, &baseVirtAddr, &virtSize);
  if (FLD_TEST_DRF(OS46, _FLAGS, _DMA_OFFSET_FIXED, _TRUE, pDmaMappingInfo->Flags))
  {
      // Fixed offset indicates an absolute virtual address.
      vaddr = pDmaMappingInfo->DmaOffset;
  }
  else
  {
      // Otherwise the offset is relative to the target virtual allocation.
      vaddr = baseVirtAddr + pDmaMappingInfo->DmaOffset;
  }
  ```

---

## 3. Physical Memory Management

### 3.1 Physical Address Translation

**Core Function**: `dmaXlateVAtoPAforChannel()` - Translates virtual addresses to physical addresses

**Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:2981-3012`

**Implementation**:
```c
dmaXlateVAtoPAforChannel_GM107(
    OBJGPU           *pGpu,
    VirtMemAllocator *pDma,
    KernelChannel    *pKernelChannel,
    NvU64             vAddr,
    NvU64            *pAddr,
    NvU32            *memType
)
{
    MMU_TRACE_ARG arg      = {0};
    MMU_TRACE_PARAM params = {0};
    NV_STATUS status;

    params.mode    = MMU_TRACE_MODE_TRANSLATE;
    params.va      = vAddr;
    params.vaLimit = vAddr;
    params.pArg    = &arg;

    status = mmuTrace(pGpu, pKernelChannel->pVAS, &params);
    if (status == NV_OK)
    {
        *memType = arg.aperture;
        *pAddr = arg.pa;
    }

    return status;
}
```

**Usage**:
- **Evidence**: `src/nvidia/src/kernel/gpu/rc/kernel_rc_misc.c:79`
  ```c
  dmaXlateVAtoPAforChannel_HAL(pGpu, pDma, pKernelChannel, virtAddr, &physaddr, &memtype)
  ```

### 3.2 Memory Descriptors

**Structure**: `MEMORY_DESCRIPTOR` - Represents physical memory allocations

**Key Operations**:
- `memdescGetPhysAddr()` - Get physical address
- `memdescGetPteArray()` - Get page table entry array
- `memdescGetPageSize()` - Get page size
- `memdescGetSize()` - Get memory size

**Evidence**: Used extensively in `dmaMapBuffer_GM107()`:
- Line 2752: `pageSizeSubDev = memdescGetPageSize(pSubDevMemDesc, VAS_ADDRESS_TRANSLATION(pVAS));`
- Line 2753: `pageOffsSubDev = memdescGetPhysAddr(pSubDevMemDesc, VAS_ADDRESS_TRANSLATION(pVAS), 0)`
- Line 2781: `mapLength = RM_ALIGN_UP(pageOffs + memdescGetSize(pMemDesc), pageSize);`

---

## 4. Page Table Manipulations

### 4.1 Page Table Update Operations

**Core Function**: `dmaUpdateVASpace()` - Updates page table entries (PTEs) for virtual address mappings

**Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:2175-3093`

**Function Signature**:
```c
dmaUpdateVASpace_GF100(
    OBJGPU     *pGpu,
    VirtMemAllocator *pDma,
    OBJVASPACE *pVAS,
    MEMORY_DESCRIPTOR *pMemDesc,
    NvU8       *pTgtPteMem,                // CPU pointer to PTE memory
    NvU64       vAddr,                      // Virtual address start
    NvU64       vAddrLimit,                 // Virtual address limit
    NvU32       flags,                      // Update flags
    DMA_PAGE_ARRAY *pPageArray,            // Physical page array
    NvU32       overmapPteMod,
    COMPR_INFO *pComprInfo,
    NvU64       surfaceOffset,
    NvU32       valid,
    GMMU_APERTURE aperture,
    NvBool      isVolatile,
    NvU32       peer,
    NvU64       fabricAddr,
    NvU32       deferInvalidate,
    NvBool      bSparse,
    NvU64       pageSize
)
```

**Key Operations**:

1. **PTE Attribute Setup**:
   - **Evidence**: Lines 2233-2238
     ```c
     priv = (flags & DMA_UPDATE_VASPACE_FLAGS_PRIV) ? NV_MMU_PTE_PRIVILEGE_TRUE : NV_MMU_PTE_PRIVILEGE_FALSE;
     tlbLock = (flags & DMA_UPDATE_VASPACE_FLAGS_TLB_LOCK) ? NV_MMU_PTE_LOCK_TRUE : NV_MMU_PTE_LOCK_FALSE;
     readOnly = (flags & DMA_UPDATE_VASPACE_FLAGS_READ_ONLY) ? NV_MMU_PTE_READ_ONLY_TRUE : NV_MMU_PTE_READ_ONLY_FALSE;
     writeDisable = !!(flags & DMA_UPDATE_VASPACE_FLAGS_SHADER_READ_ONLY);
     readDisable = !!(flags & DMA_UPDATE_VASPACE_FLAGS_SHADER_WRITE_ONLY);
     ```

2. **Page Size Validation**:
   - **Evidence**: Lines 2242-2246
     ```c
     vaSpaceBigPageSize = vaspaceGetBigPageSize(pVAS);
     if ((pageSize == RM_PAGE_SIZE_64K) || (pageSize == RM_PAGE_SIZE_128K))
     {
         NV_ASSERT_OR_RETURN(pageSize == vaSpaceBigPageSize, NV_ERR_INVALID_STATE);
     }
     ```

3. **PTE Update Type Determination**:
   - **Evidence**: Lines 2254-2255
     ```c
     update_type = (bUnmap || (NV_MMU_PTE_LOCK_FALSE == tlbLock)
                     || (NV_MMU_PTE_READ_ONLY_TRUE == readOnly)) ? PTE_DOWNGRADE : PTE_UPGRADE;
     ```

### 4.2 MMU Page Table Walk Operations

**Core Library**: MMU walk framework for hierarchical page table traversal

**Evidence**: `src/nvidia/src/libraries/mmu/mmu_walk.c`

**Key Functions**:

1. **MMU Walk Creation**:
   - **Evidence**: Lines 83-127
     ```c
     NV_STATUS mmuWalkCreate(
         const MMU_FMT_LEVEL      *pRootFmt,
         MMU_WALK_USER_CTX        *pUserCtx,
         const MMU_WALK_CALLBACKS *pCb,
         const MMU_WALK_FLAGS      flags,
         MMU_WALK                **ppWalk,
         MMU_WALK_MEMDESC         *pStagingBuffer
     )
     ```

2. **MMU Walk Map Operation**:
   - **Evidence**: `src/nvidia/src/libraries/mmu/mmu_walk_map.c:40-89`
     ```c
     NV_STATUS mmuWalkMap(
         MMU_WALK             *pWalk,
         const NvU64           vaLo,
         const NvU64           vaHi,
         const MMU_MAP_TARGET *pTarget
     )
     ```

   **Mapping Process**:
   - **Evidence**: Lines 97-180
     - Acquires root page directory entry (PDE)
     - Traverses page table hierarchy
     - Maps entries at target page level
     - Updates state tracker for mapped entries

3. **PDE (Page Directory Entry) Operations**:
   - **Evidence**: `src/nvidia/src/libraries/mmu/mmu_walk.c:55-63`
     ```c
     static NV_STATUS NV_NOINLINE
     _mmuWalkPdeAcquire(const MMU_WALK *pWalk, const MMU_WALK_OP_PARAMS *pOpParams,
                        MMU_WALK_LEVEL *pLevel, MMU_WALK_LEVEL_INST *pLevelInst,
                        const NvU32 entryIndex, const NvU32 subLevel,
                        const NvU64 vaLo, const NvU64 vaHi,
                        MMU_WALK_LEVEL_INST *pSubLevelInsts[])
     ```

### 4.3 Page Table Entry (PTE) Information

**Core Functions**:
- `vaspaceGetPteInfo()` - Retrieves PTE information
  - **Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:327`
    ```c
    NV_STATUS (*__vaspaceGetPteInfo__)(struct OBJVASPACE * /*this*/, struct OBJGPU *, NV0080_CTRL_DMA_GET_PTE_INFO_PARAMS *, RmPhysAddr *);
    ```

- `vaspaceSetPteInfo()` - Sets PTE information
  - **Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:328`
    ```c
    NV_STATUS (*__vaspaceSetPteInfo__)(struct OBJVASPACE * /*this*/, struct OBJGPU *, NV0080_CTRL_DMA_SET_PTE_INFO_PARAMS *);
    ```

**Control Interface**:
- **Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/dma.c:266-292`
  ```c
  NV_STATUS deviceCtrlCmdDmaGetPteInfo_IMPL(
      Device *pDevice,
      NV0080_CTRL_DMA_GET_PTE_INFO_PARAMS *pParams
  )
  {
      OBJGPU         *pGpu = GPU_RES_GET_GPU(pDevice);
      OBJVASPACE     *pVAS = NULL;
      NV_STATUS       status = NV_OK;
      ...
      status = vaspaceGetPteInfo(pVAS, pGpu, pParams, NULL);
      ...
  }
  ```

### 4.4 TLB (Translation Lookaside Buffer) Invalidation

**Core Function**: `vaspaceInvalidateTlb()` - Invalidates TLB entries

**Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:325`
```c
void (*__vaspaceInvalidateTlb__)(struct OBJVASPACE * /*this*/, struct OBJGPU *, VAS_PTE_UPDATE_TYPE);
```

**Update Types**:
- **Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:122-126`
  ```c
  typedef enum
  {
      PTE_UPGRADE,
      PTE_DOWNGRADE
  } VAS_PTE_UPDATE_TYPE;
  ```

**Usage Example**:
- **Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:3062`
  ```c
  gvaspaceInvalidateTlb(pGVAS, pGpu, PTE_UPGRADE);
  ```

---

## 5. Integration Points

### 5.1 Virtual Address Space to Page Table Connection

**Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:3055-3056`
```c
NV_ASSERT_OK_OR_RETURN(mmuWalkMap(userCtx.pGpuState->pWalk,
                                  vaLo, vaHi, &mapTarget));
```

### 5.2 Buffer Mapping to Page Table Updates

**Flow**:
1. `dmaMapBuffer()` allocates VA and prepares page array
2. `dmaUpdateVASpace()` updates page tables with physical addresses
3. TLB invalidation ensures coherency

**Evidence**: `src/nvidia/src/kernel/gpu/mem_mgr/arch/maxwell/virt_mem_allocator_gm107.c:2865-2889`
```c
status = dmaUpdateVASpace_HAL(pGpu, pDma, pVAS,
                               pSubDevMemDesc,
                               NULL,  // tgtPteMem
                               vaddr,
                               vaddr + mapLength - 1,
                               flags,
                               &pageArray,
                               ...
```

### 5.3 Physical Memory to Virtual Address Mapping

**Complete Flow**:
1. **Physical Memory Allocation**: `MEMORY_DESCRIPTOR` created with physical pages
2. **Virtual Address Allocation**: `vaspaceAlloc()` allocates VA range
3. **Page Table Population**: `dmaUpdateVASpace()` creates VA→PA mappings
4. **TLB Synchronization**: `vaspaceInvalidateTlb()` ensures visibility

**Evidence**: Complete flow in `dmaMapBuffer_GM107()`:
- Lines 2830-2836: VA allocation
- Lines 2845-2850: Page array initialization
- Lines 2865-2889: Page table update

---

## 6. Key Data Structures

### 6.1 Virtual Address Space Structure

**Evidence**: `src/nvidia/generated/g_vaspace_nvoc.h:254-260`
- `vasStart`: Start of virtual address range
- `vasLimit`: End of virtual address range
- `refCnt`: Reference count for the address space

### 6.2 Page Table Entry Array

**Structure**: `DMA_PAGE_ARRAY`
- **Evidence**: `src/nvidia/generated/g_virt_mem_allocator_nvoc.h:582`
  ```c
  typedef struct _def_dma_page_array
  {
      NvU32      count;      //!< Number of pages
      void       *pData;     //!< Array of PTE addresses or opaque OS-specific data.
      ...
  } DMA_PAGE_ARRAY;
  ```

### 6.3 MMU Walk Context

**Structure**: `MMU_WALK`
- **Evidence**: `src/nvidia/src/libraries/mmu/mmu_walk.c:83-127`
  - Manages hierarchical page table traversal
  - Maintains state for PDE/PTE operations
  - Handles staging buffers for page table updates

---

## 7. Summary of Key Functions

| Function | Purpose | File Reference |
|----------|---------|----------------|
| `vaspaceAlloc()` | Allocate virtual address range | `vaspace.c:52-157` |
| `vaspaceFree()` | Free virtual address range | `g_vaspace_nvoc.h:303` |
| `vaspaceMap()` | Map virtual address to physical memory | `g_vaspace_nvoc.h:310` |
| `vaspaceUnmap()` | Unmap virtual address | `g_vaspace_nvoc.h:311` |
| `dmaMapBuffer()` | Map buffer to virtual address | `virt_mem_allocator_gm107.c:2701` |
| `dmaUnmapBuffer()` | Unmap buffer from virtual address | `virt_mem_allocator_gm107.c:2902` |
| `dmaUpdateVASpace()` | Update page table entries | `virt_mem_allocator_gm107.c:2175` |
| `dmaXlateVAtoPAforChannel()` | Translate VA to PA | `virt_mem_allocator_gm107.c:2981` |
| `mmuWalkMap()` | MMU page table walk for mapping | `mmu_walk_map.c:40` |
| `vaspaceInvalidateTlb()` | Invalidate TLB entries | `g_vaspace_nvoc.h:325` |

---

## 8. Code Flow Examples

### 8.1 Complete Buffer Mapping Flow

```
1. dmaMapBuffer_GM107()
   ├─ Calculate VA size and alignment (lines 2781-2793)
   ├─ vaspaceAlloc() - Allocate VA range (line 2830)
   ├─ dmaPageArrayInit() - Initialize page array (line 2845)
   └─ dmaUpdateVASpace_HAL() - Update page tables (line 2865)
       ├─ Fill PTE entries with physical addresses
       ├─ Set PTE attributes (privilege, read-only, etc.)
       └─ Invalidate TLB if needed
```

### 8.2 Virtual Address Translation Flow

```
1. dmaXlateVAtoPAforChannel_GM107()
   ├─ Setup MMU_TRACE_PARAM with virtual address
   ├─ mmuTrace() - Walk page tables
   │   ├─ Traverse page directory hierarchy
   │   ├─ Find corresponding PTE
   │   └─ Extract physical address and aperture
   └─ Return physical address and memory type
```

---

## Conclusion

This analysis demonstrates a comprehensive virtual memory management system with:
- **Virtual Address Management**: Allocation, deallocation, and range management
- **Buffer Mapping**: Integration between virtual addresses and physical memory buffers
- **Page Table Operations**: Hierarchical page table traversal and PTE manipulation
- **Physical Memory Translation**: VA→PA translation for channel operations
- **TLB Management**: Coherency maintenance through TLB invalidation

All components are tightly integrated through well-defined interfaces and follow consistent patterns across the codebase.
