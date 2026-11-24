"""Tab order change for drag and drop. PURE logic.

TABS is a list of objects with a "pinned" attribute. Pinned tabs stay first.
"""


def move_tab(tabs, tab, target=None, after=False, pin=None):
    """Move TAB next to TARGET (before it, or after it if AFTER is true).

    With no TARGET, move TAB to the end of its group. PIN, if not None,
    sets the pinned state of TAB first. Return True if the list changed.
    """
    if tab not in tabs or target is tab:
        return False
    before = list(tabs), tab.pinned
    tabs.remove(tab)
    if pin is not None:
        tab.pinned = bool(pin)
    if target is None or target not in tabs:
        count = sum(1 for t in tabs if t.pinned)
        index = count if tab.pinned else len(tabs)
        if tab.pinned:
            # Put it after the last pinned tab.
            index = max(i for i, t in enumerate(tabs) if t.pinned) + 1 if count else 0
    else:
        index = tabs.index(target) + (1 if after else 0)
    tabs.insert(index, tab)
    tabs.sort(key=lambda t: not t.pinned)
    return (list(tabs), tab.pinned) != before
