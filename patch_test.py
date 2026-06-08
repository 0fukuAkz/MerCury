import re

with open('tests/test_error_handling.py', 'r') as f:
    lines = f.readlines()

# Re-indent everything from line 108 to 120 (0-indexed 107 to 119)
for i in range(108, 120):
    if lines[i].startswith('        '):
        lines[i] = '    ' + lines[i]

with open('tests/test_error_handling.py', 'w') as f:
    f.writelines(lines)

