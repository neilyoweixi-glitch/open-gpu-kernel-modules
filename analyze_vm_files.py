#!/usr/bin/env python3
import os
import re

# Read the file list
with open('vm_files_list.txt', 'r') as f:
    lines = f.readlines()

files = []
current_category = ""

for line in lines:
    line = line.strip()
    if not line or line.startswith('#'):
        if line.startswith('##'):
            current_category = line.replace('#', '').strip()
        continue
    
    if os.path.exists(line):
        files.append((line, current_category))

# Categorize files
c_files = []
h_files = []
generated_files = []

for filepath, category in files:
    if filepath.endswith('.c'):
        c_files.append((filepath, category))
    elif filepath.endswith('.h'):
        h_files.append((filepath, category))
    
    if 'generated' in filepath:
        generated_files.append((filepath, category))

def count_lines(filepath):
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

print("=" * 80)
print("VIRTUAL MEMORY MANAGEMENT FILES ANALYSIS")
print("=" * 80)
print()

# Count totals
total_c_files = len(c_files)
total_h_files = len(h_files)
total_files = total_c_files + total_h_files

print(f"Total Files: {total_files}")
print(f"  - C Source Files: {total_c_files}")
print(f"  - Header Files: {total_h_files}")
print()

# Calculate statistics
c_total_lines = 0
h_total_lines = 0
c_code_lines = 0
h_code_lines = 0

print("=" * 80)
print("DETAILED FILE BREAKDOWN BY CATEGORY")
print("=" * 80)
print()

categories = {}
for filepath, category in files:
    if category not in categories:
        categories[category] = {'c': [], 'h': []}
    
    if filepath.endswith('.c'):
        categories[category]['c'].append(filepath)
    elif filepath.endswith('.h'):
        categories[category]['h'].append(filepath)

for category, files_dict in sorted(categories.items()):
    if not files_dict['c'] and not files_dict['h']:
        continue
    
    print(f"\n{category}")
    print("-" * 80)
    
    c_lines = 0
    h_lines = 0
    c_code = 0
    h_code = 0
    
    for filepath in sorted(files_dict['c']):
        lines = count_lines(filepath)
        code = count_code_lines(filepath)
        c_lines += lines
        c_code += code
        c_total_lines += lines
        c_code_lines += code
        rel_path = filepath.replace('./src/', '')
        print(f"  C:  {rel_path:70s} {lines:6d} lines ({code:6d} code)")
    
    for filepath in sorted(files_dict['h']):
        lines = count_lines(filepath)
        code = count_code_lines(filepath)
        h_lines += lines
        h_code += code
        h_total_lines += lines
        h_code_lines += code
        rel_path = filepath.replace('./src/', '')
        print(f"  H:  {rel_path:70s} {lines:6d} lines ({code:6d} code)")
    
    if c_lines > 0 or h_lines > 0:
        print(f"  Category Total: {c_lines + h_lines:6d} lines ({c_code + h_code:6d} code)")

print()
print("=" * 80)
print("SUMMARY STATISTICS")
print("=" * 80)
print()

print(f"C Source Files:")
print(f"  Total Files: {total_c_files}")
print(f"  Total Lines: {c_total_lines:,}")
print(f"  Code Lines:  {c_code_lines:,}")
print(f"  Avg per File: {c_total_lines // total_c_files if total_c_files > 0 else 0:,}")
print()

print(f"Header Files:")
print(f"  Total Files: {total_h_files}")
print(f"  Total Lines: {h_total_lines:,}")
print(f"  Code Lines:  {h_code_lines:,}")
print(f"  Avg per File: {h_total_lines // total_h_files if total_h_files > 0 else 0:,}")
print()

print(f"Overall Totals:")
print(f"  Total Files: {total_files}")
print(f"  Total Lines: {c_total_lines + h_total_lines:,}")
print(f"  Code Lines:  {c_code_lines + h_code_lines:,}")
print()

# Generated vs non-generated
generated_c = [f for f, _ in c_files if 'generated' in f]
generated_h = [f for f, _ in h_files if 'generated' in f]
non_generated_c = [f for f, _ in c_files if 'generated' not in f]
non_generated_h = [f for f, _ in h_files if 'generated' not in f]

gen_c_lines = sum(count_lines(f) for f in generated_c)
gen_h_lines = sum(count_lines(f) for f in generated_h)
non_gen_c_lines = sum(count_lines(f) for f in non_generated_c)
non_gen_h_lines = sum(count_lines(f) for f in non_generated_h)

print("=" * 80)
print("GENERATED vs NON-GENERATED FILES")
print("=" * 80)
print()
print(f"Generated Files:")
print(f"  C Files: {len(generated_c):3d} files, {gen_c_lines:7,} lines")
print(f"  H Files: {len(generated_h):3d} files, {gen_h_lines:7,} lines")
print(f"  Total:   {len(generated_c) + len(generated_h):3d} files, {gen_c_lines + gen_h_lines:7,} lines")
print()
print(f"Non-Generated Files:")
print(f"  C Files: {len(non_generated_c):3d} files, {non_gen_c_lines:7,} lines")
print(f"  H Files: {len(non_generated_h):3d} files, {non_gen_h_lines:7,} lines")
print(f"  Total:   {len(non_generated_c) + len(non_generated_h):3d} files, {non_gen_c_lines + non_gen_h_lines:7,} lines")
print()

# Top 10 largest files
print("=" * 80)
print("TOP 10 LARGEST FILES")
print("=" * 80)
print()

all_files_with_size = [(f, count_lines(f)) for f, _ in files]
all_files_with_size.sort(key=lambda x: x[1], reverse=True)

for i, (filepath, lines) in enumerate(all_files_with_size[:10], 1):
    rel_path = filepath.replace('./src/', '')
    print(f"{i:2d}. {rel_path:70s} {lines:7,} lines")
