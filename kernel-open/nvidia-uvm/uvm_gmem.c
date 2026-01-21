#include <linux/mm.h>

#include "uvm_gmem.h"

#include "uvm_hal_types.h"
#include "uvm_hal.h"
#include "uvm_va_space.h"
#include "uvm_mmu.h"
#include "nv_uvm_interface.h"

NV_STATUS (*gpu_uvm_service_fault)(struct mm_struct *mm, NvU64 fault_address, struct device *gpu_dev) = NULL;
EXPORT_SYMBOL_GPL(gpu_uvm_service_fault);

NvU64 uvm_phy_mem_alloc(gpu_fault_context_t *context)
{
    NV_STATUS status;
    UvmPmaAllocationOptions options = {0};
    UvmGpuPointer pa;
    uvm_gpu_t *gpu = context->gpu;
    uvm_pmm_gpu_t *pmm = &gpu->pmm;

    options.flags = UVM_PMA_ALLOCATE_DONT_EVICT | UVM_PMA_ALLOCATE_PINNED;
    status = nvUvmInterfacePmaAllocPages(pmm->pma, 1, UVM_CHUNK_SIZE_2M, &options, &pa);
    if (status != NV_OK) {
        UVM_ERR_PRINT("gmem alloc phys mem error status = %d (%s)\n", status, nvstatusToString(status));
        return 0;
    }

    return pa;
}
EXPORT_SYMBOL_GPL(uvm_phy_mem_alloc);

void uvm_phy_mem_free(gpu_fault_context_t *context, NvU64 pa)
{
    NvU32 flags = 0;
    uvm_gpu_t *gpu = context->gpu;
    uvm_pmm_gpu_t *pmm = &gpu->pmm;

    nvUvmInterfacePmaFreePages(pmm->pma, &pa, 1, UVM_CHUNK_SIZE_2M, flags);
    return;
}
EXPORT_SYMBOL_GPL(uvm_phy_mem_free);

void uvm_memcpy(gpu_fault_context_t *context, uvm_gpu_address_t src_addr, uvm_gpu_address_t dst_addr, NvU64 size)
{
    uvm_push_t push_mem_copy;
    uvm_gpu_t *gpu = context->gpu;
    uvm_parent_gpu_t *parent_gpu = gpu->parent;
    uvm_channel_type_t channel_type;

    if (src_addr.aperture == dst_addr.aperture) {               // DtoD
            channel_type = UVM_CHANNEL_TYPE_GPU_INTERNAL;
    } else {                                                    // DtoH  HtoD
            channel_type = UVM_CHANNEL_TYPE_CPU_TO_GPU;
    }

    uvm_push_begin_acquire(gpu->channel_manager,
                            channel_type,
                            NULL,
                            &push_mem_copy,
                            "Copy from %s to %s for block [0x%llx, 0x%llx]",
                            "0: CPU",
                            gpu->name,
                            (unsigned long long)0x100000000000,
                            (unsigned long long)0x100000000000 + size);

    parent_gpu->ce_hal->memcopy(&push_mem_copy, dst_addr, src_addr, size);
    uvm_push_end_and_wait(&push_mem_copy);

    return;
}
EXPORT_SYMBOL_GPL(uvm_memcpy);

void uvm_memzero(gpu_fault_context_t *context, uvm_gpu_address_t addr)
{
    uvm_push_t push_mem_zero;
    uvm_gpu_t *gpu = context->gpu;
    uvm_gpu_address_t memset_addr;
    memset_addr = uvm_gpu_address_copy(gpu, uvm_gpu_phys_address(UVM_APERTURE_VID, addr.address));

    uvm_push_begin(gpu->channel_manager,
                    UVM_CHANNEL_TYPE_GPU_INTERNAL,
                    &push_mem_zero,
                    "Zero mem [0x%llx, 0x%llx]",
                    memset_addr.address,
                    (unsigned long long)memset_addr.address + UVM_PAGE_SIZE_2M);

    gpu->parent->ce_hal->memset_8(&push_mem_zero, memset_addr, 0, UVM_PAGE_SIZE_2M);

    uvm_push_end_and_wait(&push_mem_zero);
    return;
}
EXPORT_SYMBOL_GPL(uvm_memzero);

NvU64 uvm_pagetable_set(gpu_fault_context_t *context, NvU64 va, NvU64 pa)
{
    uvm_va_space_t *va_space = context->uvm_va_space;
    uvm_gpu_t *gpu = context->gpu;
    uvm_gpu_va_space_t *gpu_va_space = va_space->gpu_va_spaces[uvm_id_gpu_index(gpu->id)];
    uvm_page_tree_t *page_tables = &gpu_va_space->page_tables;
    uvm_page_table_range_t local_range;
    NV_STATUS status;

    status = uvm_page_tree_get_ptes(page_tables,
                           UVM_PAGE_SIZE_2M,
                           va,
                           UVM_PAGE_SIZE_2M,
                           UVM_PMM_ALLOC_FLAGS_NONE,
                           &local_range);
    if (status != NV_OK) {
        UVM_ERR_PRINT("gmem get ptes error status = %d (%s)\n", status, nvstatusToString(status));
        return 0;
    }

    uvm_push_t push_pagetable;
    uvm_prot_t new_prot = UVM_PROT_READ_WRITE_ATOMIC;

    status = uvm_push_begin_acquire(gpu->channel_manager,
                                    UVM_CHANNEL_TYPE_MEMOPS,
                                    NULL,
                                    &push_pagetable,
                                    "Mapping pages in block [0x%llx, 0x%llx) as %s",
                                    (unsigned long long)va,
                                    (unsigned long long)va + UVM_PAGE_SIZE_2M, // + 1,
                                    uvm_prot_string(new_prot));
    if (status != NV_OK) {
        UVM_ERR_PRINT("begin mapping pages status = %d (%s)\n", status, nvstatusToString(status));
        return 0;
    }

    uvm_pte_batch_t pte_batch;
    uvm_tlb_batch_t tlb_batch;
    // Write the new permissions
    uvm_pte_batch_begin(&push_pagetable, &pte_batch);
    uvm_tlb_batch_begin(page_tables, &tlb_batch);

    uvm_gpu_phys_address_t pte_addr = uvm_page_table_range_entry_address(page_tables, &local_range, 0);
    NvU32 pte_size = uvm_mmu_pte_size(page_tables, UVM_PAGE_SIZE_2M);
    NvU64 pte_val;
    NvU64 pte_flags = UVM_MMU_PTE_FLAGS_NONE;

    pte_val = page_tables->hal->make_pte(UVM_APERTURE_VID, pa, new_prot, pte_flags);
    uvm_pte_batch_write_pte(&pte_batch, pte_addr, pte_val, pte_size);
    uvm_tlb_batch_invalidate(&tlb_batch, va, UVM_PAGE_SIZE_2M, UVM_PAGE_SIZE_2M, UVM_MEMBAR_NONE);

    uvm_pte_batch_end(&pte_batch);
    uvm_tlb_batch_end(&tlb_batch, &push_pagetable, UVM_MEMBAR_GPU);

    uvm_push_end_and_wait(&push_pagetable);

    return pte_addr.address;
}
EXPORT_SYMBOL_GPL(uvm_pagetable_set);

#define page_tree_begin_acquire(tree, tracker, push, format, ...) ({                                                            \
    NV_STATUS __status;                                                                                                         \
    uvm_channel_manager_t *__manager = (tree)->gpu->channel_manager;                                                            \
                                                                                                                                \
    if (__manager == NULL)                                                                                                      \
        __status = uvm_push_begin_fake((tree)->gpu, (push));                                                                    \
    else if (uvm_parent_gpu_is_virt_mode_sriov_heavy((tree)->gpu->parent))                                                      \
        __status = uvm_push_begin_acquire(__manager, UVM_CHANNEL_TYPE_MEMOPS, (tracker), (push), (format), ##__VA_ARGS__);      \
    else                                                                                                                        \
        __status = uvm_push_begin_acquire(__manager, UVM_CHANNEL_TYPE_GPU_INTERNAL, (tracker), (push), (format), ##__VA_ARGS__);\
                                                                                                                                \
    __status;                                                                                                                   \
})

void uvm_pagetable_clear(gpu_fault_context_t *context, NvU64 va, NvU64 pte_addr)
{
    uvm_va_space_t *va_space = context->uvm_va_space;
    uvm_gpu_t *gpu = context->gpu;
    uvm_gpu_va_space_t *gpu_va_space = va_space->gpu_va_spaces[uvm_id_gpu_index(gpu->id)];
    uvm_page_tree_t *page_tables = &gpu_va_space->page_tables;
    NV_STATUS status = NV_OK;
    uvm_push_t push;
    uvm_pte_batch_t pte_batch;
    uvm_tlb_batch_t tlb_batch;
    NvU32 entry_size = uvm_mmu_pte_size(page_tables, UVM_PAGE_SIZE_2M);
    uvm_gpu_phys_address_t entry_addr;

    status = page_tree_begin_acquire(page_tables, NULL, &push, "Clearing PTEs for [0x%llx, 0x%llx)",
                    va, va + UVM_PAGE_SIZE_2M);
    if (status != NV_OK)
        return;

    uvm_pte_batch_begin(&push, &pte_batch);
    uvm_tlb_batch_begin(page_tables, &tlb_batch);

    entry_addr.aperture = UVM_APERTURE_VID;
    entry_addr.address = pte_addr;
    uvm_pte_batch_clear_ptes(&pte_batch, entry_addr, 0, entry_size, 1);
    uvm_tlb_batch_invalidate(&tlb_batch, va, UVM_PAGE_SIZE_2M, UVM_PAGE_SIZE_2M, UVM_MEMBAR_NONE);

    uvm_pte_batch_end(&pte_batch);
    uvm_tlb_batch_end(&tlb_batch, &push, UVM_MEMBAR_GPU);

    uvm_push_end_and_wait(&push);

    return;
}
EXPORT_SYMBOL_GPL(uvm_pagetable_clear);

NV_STATUS uvm_channel_sync(gpu_fault_context_t *context, uvm_channel_type_t channel_type)
{
    uvm_gpu_t *gpu = context->gpu;
    uvm_channel_t *channel;
    uvm_tracker_entry_t tracker_entry;
    NV_STATUS status = NV_OK;

    uvm_channel_reserve_type(gpu->channel_manager, channel_type, &channel);
    if (!channel) {
        return NV_ERR_INVALID_ARGUMENT;
    }

    // 构造一个tracker entry，用于跟踪最新的任务
    tracker_entry.channel = channel;
    tracker_entry.value = channel->tracking_sem.queued_value;

    status = uvm_tracker_wait_for_entry(&tracker_entry);

    return status;
}
EXPORT_SYMBOL_GPL(uvm_channel_sync);