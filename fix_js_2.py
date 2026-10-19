import pathlib
p = pathlib.Path('static/project-window.js')
text = p.read_text(encoding='utf-8')
target = """      var filesOpen = false;
      var detailEl = document.getElementById('projectFilesDetails');
      if (detailEl) {
        filesOpen = detailEl.open;
      }
      var board = document.getElementById('kanbanBoard');
      if (!board) return;                    // guard: container absent
      board.innerHTML = data.html;
      var newDetailEl = document.getElementById('projectFilesDetails');
      if (newDetailEl && filesOpen) {
        newDetailEl.open = true;
      }"""

repl = """      var filesOpen = false;
      var detailEl = document.getElementById('projectFilesDetails');
      if (detailEl) {
        filesOpen = detailEl.open;
      }
      
      var openGandalfRuns = {};
      var gruns = document.querySelectorAll('#gandalfPanel .grun.open');
      for (var i = 0; i < gruns.length; i++) {
        var runId = gruns[i].getAttribute('data-run');
        var gexec = gruns[i].querySelector('.gexec');
        if (runId && gexec && gexec.getAttribute('data-loaded') === '1') {
          openGandalfRuns[runId] = gexec.innerHTML;
        }
      }

      var board = document.getElementById('kanbanBoard');
      if (!board) return;                    // guard: container absent
      board.innerHTML = data.html;
      
      var newDetailEl = document.getElementById('projectFilesDetails');
      if (newDetailEl && filesOpen) {
        newDetailEl.open = true;
      }
      
      for (var runId in openGandalfRuns) {
        var el = document.querySelector('#gandalfPanel .grun[data-run="' + runId + '"]');
        if (el) {
          el.classList.add('open');
          var gexec = el.querySelector('.gexec');
          if (gexec) {
            gexec.setAttribute('data-loaded', '1');
            gexec.innerHTML = openGandalfRuns[runId];
          }
        }
      }"""

if target in text:
    print('Found and replacing (LF)')
    text = text.replace(target, repl)
elif target.replace('\n', '\r\n') in text:
    print('Found and replacing (CRLF)')
    text = text.replace(target.replace('\n', '\r\n'), repl.replace('\n', '\r\n'))
else:
    print('Target not found')

p.write_text(text, encoding='utf-8')
