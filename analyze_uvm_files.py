#!/usr/bin/env python3
import os
import re
from collections import defaultdict

# UVM file categories
uvm_files = {
    'kernel-open/nvidia-uvm': [],
    'src/nvidia/src/kernel/gpu/uvm': [],
    'src/nvidia/inc/kernel/gpu/uvm': [],
    'src/nvidia/src/kernel/gpu/mmu': [],  # uvm_sw files
    'src/nvidia/src/kernel/gpu/fifo': [],  # uvm_channel_retainer
    'src/nvidia/generated': [],  # Generated UVM files
}

def find_uvm_files():
    """Find all UVM-related files"""
    files = []
    
    # kernel-open/nvidia-uvm directory
    uvm_dir = '/workspace/kernel-open/nvidia-uvm'
    if os.path.exists(uvm_dir):
        for root, dirs, filenames in os.walk(uvm_dir):
            for filename in filenames:
                if filename.endswith(('.c', '.h')):
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, '/workspace')
                    files.append(('kernel-open/nvidia-uvm', rel_path, filepath))
    
    # src/nvidia UVM files
    uvm_src_dirs = [
        '/workspace/src/nvidia/src/kernel/gpu/uvm',
        '/workspace/src/nvidia/inc/kernel/gpu/uvm',
        '/workspace/src/nvidia/src/kernel/gpu/mmu',
        '/workspace/src/nvidia/src/kernel/gpu/fifo',
    ]
    
    for uvm_dir in uvm_src_dirs:
        if os.path.exists(uvm_dir):
            category = os.path.relpath(uvm_dir, '/workspace/src/nvidia')
            for root, dirs, filenames in os.walk(uvm_dir):
                for filename in filenames:
                    if filename.endswith(('.c', '.h')) and 'uvm' in filename.lower():
                        filepath = os.path.join(root, filename)
                        rel_path = os.path.relpath(filepath, '/workspace')
                        files.append((category, rel_path, filepath))
    
    # Generated UVM files
    generated_dir = '/workspace/src/nvidia/generated'
    if os.path.exists(generated_dir):
        for filename in os.listdir(generated_dir):
            if filename.endswith(('.c', '.h')) and 'uvm' in filename.lower():
                filepath = os.path.join(generated_dir, filename)
                rel_path = os.path.relpath(filepath, '/workspace')
                files.append(('src/nvidia/generated', rel_path, filepath))
    
    return files

def count_lines(filepath):
    """Count total lines in file"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except:
        return 0

def count_code_lines(filepath):
    """Count non-empty, non-comment lines"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            code_lines = 0
            in_multiline_comment = False
            
            for line in lines:
                stripped = line.strip()
                
                # Skip empty lines
                if not stripped:
                    continue
                
                # Handle multiline comments
                if '/*' in stripped:
                    in_multiline_comment = True
                if '*/' in stripped:
                    in_multiline_comment = False
                    continue
                
                if in_multiline_comment:
                    continue
                
                # Skip single line comments
                if stripped.startswith('//') or stripped.startswith('/*'):
                    continue
                
                code_lines += 1
            
            return code_lines
    except:
        return 0

def categorize_file(filepath, category):
    """Categorize file by functionality"""
    filename = os.path.basename(filepath).lower()
    
    if 'test' in filename or '_test' in filename:
        return 'Tests'
    elif 'fault' in filename or 'buffer' in filename:
        return 'Fault Handling'
    elif 'mmu' in filename:
        return 'MMU Operations'
    elif 'va_block' in filename or 'va_range' in filename or 'va_space' in filename:
        return 'Virtual Address Management'
    elif 'migrate' in filename or 'migration' in filename:
        return 'Migration'
    elif 'perf' in filename or 'prefetch' in filename or 'heuristics' in filename:
        return 'Performance'
    elif 'channel' in filename or 'push' in filename or 'semaphore' in filename:
        return 'Channel/Synchronization'
    elif 'pmm' in filename or 'mem' in filename:
        return 'Memory Management'
    elif 'hal' in filename or 'arch' in filename or any(x in filename for x in ['pascal', 'volta', 'turing', 'ampere', 'hopper', 'blackwell', 'maxwell']):
        return 'Architecture-Specific'
    elif 'policy' in filename or 'range_group' in filename:
        return 'Policy Management'
    elif 'ats' in filename:
        return 'ATS (Address Translation Services)'
    elif 'procfs' in filename or 'tools' in filename:
        return 'Debug/Tools'
    elif 'tracker' in filename or 'lock' in filename:
        return 'Synchronization'
    elif 'api' in filename or 'ioctl' in filename:
        return 'API/Interface'
    elif 'global' in filename or 'common' in filename:
        return 'Core/Common'
    elif category == 'src/nvidia/generated':
        return 'Generated Code'
    else:
        return 'Other'

# Find all UVM files
all_files = find_uvm_files()

# Organize by category
by_category = defaultdict(list)
by_functionality = defaultdict(list)

for category, rel_path, filepath in all_files:
    if os.path.exists(filepath):
        lines = count_lines(filepath)
        code_lines = count_code_lines(filepath)
        func_category = categorize_file(filepath, category)
        
        file_info = {
            'path': rel_path,
            'full_path': filepath,
            'lines': lines,
            'code_lines': code_lines,
            'category': category,
            'func_category': func_category
        }
        
        by_category[category].append(file_info)
        by_functionality[func_category].append(file_info)

# Print analysis
print("=" * 80)
print("NVIDIA-UVM DRIVER FILE ANALYSIS")
print("=" * 80)
print()

total_files = len(all_files)
total_lines = sum(f['lines'] for files in by_category.values() for f in files)
total_code_lines = sum(f['code_lines'] for files in by_category.values() for f in files)

print(f"Total UVM Files Found: {total_files}")
print(f"Total Lines: {total_lines:,}")
print(f"Code Lines: {total_code_lines:,}")
print()

print("=" * 80)
print("FILES BY LOCATION/CATEGORY")
print("=" * 80)
print()

for category in sorted(by_category.keys()):
    files = by_category[category]
    if not files:
        continue
    
    c_files = [f for f in files if f['path'].endswith('.c')]
    h_files = [f for f in files if f['path'].endswith('.h')]
    
    c_lines = sum(f['lines'] for f in c_files)
    h_lines = sum(f['lines'] for f in h_files)
    c_code = sum(f['code_lines'] for f in c_files)
    h_code = sum(f['code_lines'] for f in h_files)
    
    print(f"\n{category}")
    print("-" * 80)
    print(f"  C Files: {len(c_files):3d} files, {c_lines:7,} lines ({c_code:7,} code)")
    print(f"  H Files: {len(h_files):3d} files, {h_lines:7,} lines ({h_code:7,} code)")
    print(f"  Total:   {len(files):3d} files, {c_lines + h_lines:7,} lines ({c_code + h_code:7,} code)")
    
    # Show top 5 largest files
    sorted_files = sorted(files, key=lambda x: x['lines'], reverse=True)
    print(f"  Top Files:")
    for f in sorted_files[:5]:
        print(f"    {os.path.basename(f['path']):50s} {f['lines']:6,} lines")

print()
print("=" * 80)
print("FILES BY FUNCTIONALITY")
print("=" * 80)
print()

for func_cat in sorted(by_functionality.keys()):
    files = by_functionality[func_cat]
    if not files:
        continue
    
    total = sum(f['lines'] for f in files)
    code = sum(f['code_lines'] for f in files)
    
    print(f"{func_cat:30s} {len(files):3d} files, {total:7,} lines ({code:7,} code)")

print()
print("=" * 80)
print("TOP 20 LARGEST FILES")
print("=" * 80)
print()

all_file_info = []
for files in by_category.values():
    all_file_info.extend(files)

all_file_info.sort(key=lambda x: x['lines'], reverse=True)

for i, f in enumerate(all_file_info[:20], 1):
    print(f"{i:2d}. {os.path.basename(f['path']):50s} {f['lines']:7,} lines ({f['code_lines']:7,} code)")
    print(f"    {f['path']}")

print()
print("=" * 80)
print("SUMMARY STATISTICS")
print("=" * 80)
print()

c_all = [f for files in by_category.values() for f in files if f['path'].endswith('.c')]
h_all = [f for files in by_category.values() for f in files if f['path'].endswith('.h')]

print(f"C Source Files:")
print(f"  Count: {len(c_all)}")
print(f"  Total Lines: {sum(f['lines'] for f in c_all):,}")
print(f"  Code Lines: {sum(f['code_lines'] for f in c_all):,}")
print(f"  Avg per File: {sum(f['lines'] for f in c_all) // len(c_all) if c_all else 0:,}")
print()

print(f"Header Files:")
print(f"  Count: {len(h_all)}")
print(f"  Total Lines: {sum(f['lines'] for f in h_all):,}")
print(f"  Code Lines: {sum(f['code_lines'] for f in h_all):,}")
print(f"  Avg per File: {sum(f['lines'] for f in h_all) // len(h_all) if h_all else 0:,}")
print()

# Generated vs non-generated
generated = [f for files in by_category.values() for f in files if 'generated' in f['category']]
non_generated = [f for files in by_category.values() for f in files if 'generated' not in f['category']]

print(f"Generated Files:")
print(f"  Count: {len(generated)}")
print(f"  Total Lines: {sum(f['lines'] for f in generated):,}")
print()

print(f"Non-Generated Files:")
print(f"  Count: {len(non_generated)}")
print(f"  Total Lines: {sum(f['lines'] for f in non_generated):,}")
print()
