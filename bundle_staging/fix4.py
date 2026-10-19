import pathlib

p = pathlib.Path('static/project-window.js')
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)

# find line:       }
#     }
#     // v10 Wave 4 FIX 2/3:

for i in range(len(lines)):
    if '// v10 Wave 4 FIX 2/3:' in lines[i]:
        # check if lines[i-1] is just '    }\n'
        if lines[i-1].strip() == '}':
            print('Removing extra } at', i-1)
            lines.pop(i-1)
            break

p.write_text(''.join(lines), encoding='utf-8')
