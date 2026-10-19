# Workbench reports in the project Deliverables list

John's Fitness watch reports existed but were invisible in the project list. Their nested register was first moved to Fitness/DELIVERABLES.md. The existing general-terminal deliverables reader then returned the seven correct openable entries, but the project page still queried only register-all, whose effort discovery requires a steward Face.

Connected the static project page to the existing root reader through an active project terminal. Root rows appear first, existing effort rows remain, duplicate project-relative paths are suppressed, and failure of either source retains the other source with a visible retry message. No second registry, campaign marker, parser, authorization change or service restart. This is a small connection in loadDeliv; surrounding uncommitted cockpit changes belong to other work and are excluded from this commit.

Verified through the real Fitness page after the ordinary browser token prompt: 23 visible entries (seven watch entries plus 16 existing Crossfit Prep entries), a single current watch report row, actual report opening with the Ultra section, and actual PDF opening whose clicked URL served bytes matching the saved PDF. Simulated terms-reader failure retained Crossfit entries and displayed the limitation; restoring it restored the watch rows. Receipt and repeatable live check: C:/dev/Fitness/Watch Research/deliverables-visibility.json and verify-deliverables.py.

The first inline browser probe inspected a PDF viewer response as if it were raw PDF bytes; a second probe read a popup before navigation completed. The durable check waits for report headings and verifies the clicked PDF URL through the same browser request context. Those were check defects, not publication failures.

Static HTML is read on page navigation, so the verified new page requires no server restart. A project page already open before this patch must reload once to acquire the updated list function. Running terminals and report contents are unchanged.
