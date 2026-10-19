import pathlib

p = pathlib.Path('static/project-window.js')
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)

start_idx = -1
for i, line in enumerate(lines):
    if 'var filesOpen = false;' in line:
        start_idx = i
        break

if start_idx != -1:
    end_idx = start_idx
    for i in range(start_idx, len(lines)):
        if 'if (newDetailEl && filesOpen) {' in lines[i]:
            end_idx = i + 2
            break
            
    print(f'Replacing lines {start_idx} to {end_idx}')
    
    replacement = [
        '      var filesOpen = false;\n',
        '      var detailEl = document.getElementById(\'projectFilesDetails\');\n',
        '      if (detailEl) {\n',
        '        filesOpen = detailEl.open;\n',
        '      }\n',
        '      var openGandalfRuns = {};\n',
        '      var gruns = document.querySelectorAll(\'#gandalfPanel .grun.open\');\n',
        '      for (var i = 0; i < gruns.length; i++) {\n',
        '        var runId = gruns[i].getAttribute(\'data-run\');\n',
        '        var gexec = gruns[i].querySelector(\'.gexec\');\n',
        '        if (runId && gexec && gexec.getAttribute(\'data-loaded\') === \'1\') {\n',
        '          openGandalfRuns[runId] = gexec.innerHTML;\n',
        '        }\n',
        '      }\n',
        '      var board = document.getElementById(\'kanbanBoard\');\n',
        '      if (!board) return;                    // guard: container absent\n',
        '      board.innerHTML = data.html;\n',
        '      var newDetailEl = document.getElementById(\'projectFilesDetails\');\n',
        '      if (newDetailEl && filesOpen) {\n',
        '        newDetailEl.open = true;\n',
        '      }\n',
        '      for (var runId in openGandalfRuns) {\n',
        '        var el = document.querySelector(\'#gandalfPanel .grun[data-run="\' + runId + \'"]\');\n',
        '        if (el) {\n',
        '          el.classList.add(\'open\');\n',
        '          var gexec = el.querySelector(\'.gexec\');\n',
        '          if (gexec) {\n',
        '            gexec.setAttribute(\'data-loaded\', \'1\');\n',
        '            gexec.innerHTML = openGandalfRuns[runId];\n',
        '          }\n',
        '        }\n',
        '      }\n'
    ]
    
    new_lines = lines[:start_idx] + replacement + lines[end_idx:]
    p.write_text(''.join(new_lines), encoding='utf-8')
    print('Done.')
else:
    print('Not found')
