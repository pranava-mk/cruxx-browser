# Design notes: what we copy from "Search" (Office Commun)

Source: upstream `Sources/Search/*.swift` (MIT, macOS). We copy the look and
the behaviour. We do not port the code. Sizes are in points (GTK: px).

## Colours

Upstream uses grey pairs for light and dark (`Design.swift:20-48`). Each row,
pin and button grey is "ink at low alpha" (`Design.swift:84-95`). We do the
same with the Omarchy `foreground` colour, so light and dark themes both work.

| Upstream name | Meaning | Omarchy mapping (theme.py) |
| --- | --- | --- |
| ground | page, floating panels | `background` |
| frame | sidebar, strip | `background` mixed 4% with `foreground` |
| ink | main text | `foreground` |
| muted | inactive tab title | `foreground` at 55% |
| faint | "New tab" row | `foreground` at 28% |
| hairline | divider, panel border | `foreground` at 11% |
| wash | selected row, picked suggestion | `foreground` at 7.5% |
| hover | row under pointer | `foreground` at 4.5% |
| tile | pinned tile at rest | `foreground` at 4% |
| pinLive | selected pinned tile | `foreground` at 10% |
| accent (none upstream) | caret, private tab, find error | `accent`, `red` |

## Sidebar

| Item | Value | Upstream |
| --- | --- | --- |
| Width | 232 | `Design.swift:251` (`Metrics.side`) |
| Side padding | 10 | `Side.swift:293` |
| Divider | 1 wide, hairline, on inner edge | `Side.swift:401` |
| Row height | 28 | `Prefs.swift:303` |
| Row gap | 2 | `Side.swift:87` |
| Row corner radius | 9 | `Side.swift:2255` |
| Row inner layout | 10 left, mark, 8 gap, title, close slot, 7 right | `Side.swift:2165,2244` |
| Title font | 12.5, regular | `Prefs.swift:304` |
| Title colour | live: ink; hover: ink 70%; rest: muted | `Side.swift:2318-2325` |
| Selected row | filled rounded pill (wash) | `Side.swift:2308` |
| Hover row | filled rounded pill (hover) | `Side.swift:2314` |
| Close button | 15 circle, ink 7%, "x" 8 semibold, only on hover | `Side.swift:2227-2234` |
| Mark (favicon tile) | 15; icon clipped to radius 22% of size | `Icons.swift:773-778` |
| Letter fallback | rounded square, ink 6%, letter 56% of size, medium, muted | `Icons.swift:779-788` |
| Pinned tile | 34 square, gap 4, radius 9/34 of size, left aligned | `Side.swift:89-90,1964` |
| Pinned glyph | favicon 16/34 of size, or letter 12/34, medium | `Side.swift:1948-1952` |
| Pinned colours | rest: tile; hover: hover; live: pinLive | `Side.swift:1974-1978` |
| "New tab" row | plus (10 medium) + text 12.5, faint, hover = ink 70% and hover pill; 28 high | `Side.swift:2332-2372` |
| Settings button | 26 square, radius 8, glyph 11 medium, bottom-left, 10 from the edges | `Side.swift:2445-2480,1752-1753` |
| Window top | no title bar, tabs start about 12 from the top | `Design.swift:166` (strip) |

Note: the upstream screenshot shows 34 square pinned tiles, left aligned.
Current upstream code stretches tiles over the row (`Side.swift:1078-1096`).
We follow the screenshot.

Note: the macOS traffic lights take the top band upstream. GTK has no such
band, so we use a plain 12 top padding.

## Top mode (tabs across the top)

| Item | Value | Upstream |
| --- | --- | --- |
| Strip height | 36 (compact) | `Design.swift:166` |
| Tab width | 186, fixed | `Design.swift:211` |
| Tab padding | 11 left, 7 right, mark 15, gap 6, close slot 15 | `Design.swift:217-224` |
| Tab height, radius | 28, 9 | `TabBar.swift:1213,1239` |
| Pinned tab | 30 wide square | `Design.swift:240` |
| Plus button | 30 wide | `Design.swift:242` |
| Gap | 2 | `Design.swift:238` |

## Address field

There is no permanent toolbar (`AddressLine.swift:1-12`). The address line in
the column is off by default. The field shows only for Ctrl+L and for a new
tab.

| Item | Value | Upstream |
| --- | --- | --- |
| Shows when | Ctrl+L, new tab | `Omnibox.swift:81-130` |
| Place | window centre, lifted 30 (60 bottom padding) | `Omnibox.swift:118` |
| Width | 560 | `Design.swift:249` |
| Field box | 22 text + 14 air above and below = 50 high; 22 side padding | `Omnibox.swift:142-144` |
| Field look | radius 14, ground fill, hairline 1, shadow 24 blur, y 8, 6% black | `Omnibox.swift:155-167` |
| Field text | system font 15.5 | `Omnibox.swift:515` |
| Page behind (over a page) | ground at 74% over the whole page; click closes | `Omnibox.swift:94` |
| Empty tab | no cover | `Omnibox.swift:90-98` |
| Text when opened | current address, whole text selected (scheme dropped when the field puts it back) | `Address.swift:127-140` |
| Close | Esc, click outside | `AddressLine.swift:1-15` |
| Refused input | red border 35% | `Omnibox.swift:162` |

## Suggestion list

| Item | Value | Upstream |
| --- | --- | --- |
| Place | under the field, 8 gap; the field never moves when the list grows | `Omnibox.swift:106-113` |
| Box | padding 6, radius 14, ground, hairline, shadow 20 blur y 6, 7% | `Omnibox.swift:211-217` |
| Row | padding 12 x 9, radius 9, gap 10 | `Omnibox.swift:295-302` |
| Row icon | 14 mark (favicon or letter); search rows use a magnifier | `Omnibox.swift:240-263` |
| Row text | address 13 ink, title 12 muted | `Omnibox.swift:266-281` |
| Picked row | wash pill (keys); hover row = hover pill | `Omnibox.swift:297-305` |
| Bookmark end mark | small bookmark symbol at the end | `Omnibox.swift:307-312` |
| Search row | text "Search <name>" | `Omnibox.swift:377` |

## Status line (link under the pointer)

| Item | Value | Upstream |
| --- | --- | --- |
| Shape | capsule, 26 high, 11 side padding, ground fill, hairline, shadow | `StatusLine.swift:128-134` |
| Text | 12 ink, ellipsis in the middle | `StatusLine.swift:123-127` |
| Place | bottom-left of page, 10 from edges | `StatusLine.swift:141-145` |
| Max width | 60% of page, at most 640 | `StatusLine.swift:135` |
| Other corner | pointer near bottom-left: bubble moves bottom-right | `StatusLine.swift:100-107` |
| Hide delay | 0.12 s | `StatusLine.swift:78-83` |

We use the WebKit signal `mouse-target-changed`. Upstream uses a script.

## Find bar

| Item | Value | Upstream |
| --- | --- | --- |
| Shape | capsule at page top-right, 12 from top, 14 from right | `Find.swift:114-128` |
| Padding | 16 left, 8 right, 8 vertical | `Find.swift:105-107` |
| Field | 150 wide, text 12.5, placeholder "Find on page" at 30% | `Find.swift:40-60` |
| Count | 10 medium, muted; red when no match | `Find.swift:63-70` |
| Buttons | 24 square, glyph 9 semibold, muted: up, down, close | `Find.swift:75-80,146-153` |
| Border | hairline; red 35% when missed | `Find.swift:104-110` |
| Shadow | 18 blur, y 5, 10% | `Find.swift:119` |

## Tab switcher (Ctrl+K)

Upstream Ctrl+Tab is a card grid (`TabSwitcher.swift:401-500`: panel radius 12,
padding 12, hairline). Ctrl+K here is a floating list that looks like the
suggestion list. It uses the address field box (see above), with rows of
mark, title (13 ink) and host (12 muted). Match: `Fuzzy.swift:12-24`
(all words must match; one typo is forgiven), `Fuzzy.swift:35-41`
(abbreviation), `Fuzzy.swift:46-64` (word start). Our pure port is
`omnibox.fuzzy_score`.

## Motion

Upstream uses short springs (`Design.swift:Motion`). We do not animate. We
avoid layout jumps: row widgets are updated in place, and the field never
moves when the list changes.

## Not copied

Spaces, profiles, split view, groups, peek, reading ring, agent marks, unread
badges, themes, Liquid Glass, extension doors.
