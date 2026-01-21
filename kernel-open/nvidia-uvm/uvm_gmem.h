#ifndef _UVM_GMEM_H_
#define _UVM_GMEM_H_

#include "nvtypes.h"
#include "uvm_hal_types.h"
#include "uvm_forward_decl.h"
#include "nvstatus.h"
#include "uvm_channel.h"

typedef struct {
    void *uvm_va_space;
    void *gpu;
    struct device *gpu_dev;
    struct mm_struct *mm;
} gpu_fault_context_t;

extern NV_STATUS (*gpu_uvm_service_fault)(struct mm_struct *mm, NvU64 fault_address, struct device *gpu_dev);

extern NvU64 uvm_phy_mem_alloc(gpu_fault_context_t *context);
extern void uvm_phy_mem_free(gpu_fault_context_t *context, NvU64 pa);

extern void uvm_memcpy(gpu_fault_context_t *context, uvm_gpu_address_t src_addr, uvm_gpu_address_t dst_addr, NvU64 size);
extern void uvm_memzero(gpu_fault_context_t *context, uvm_gpu_address_t addr);

extern NvU64 uvm_pagetable_set(gpu_fault_context_t *context, NvU64 va, NvU64 pa);
extern void uvm_pagetable_clear(gpu_fault_context_t *context, NvU64 va, NvU64 pte_addr);

extern NV_STATUS uvm_channel_sync(gpu_fault_context_t *context, uvm_channel_type_t channel_type);

#endif  // _UVM_GMEM_H_