# Mockup della UI di C-OS

Generati con lo strumento integrato `image_gen`, il 10 ottobre 2026.
La variante **C — NeXT libero** è stata scelta dall'utente. A e B restano come confronto.

I PNG sono riferimenti di composizione e stile, non asset pronti per il C64 né prove della risoluzione o della palette effettive. La specifica in `../SPEC.md` stabilisce i vincoli del renderer: 320×200 pixel logici e cinque indici della palette C64 per la shell. L'implementazione deve ridisegnare icone e font sulla griglia reale.

## A classico-compatto

Immagine: [A-classico-compatto.png](mockups/A-classico-compatto.png)

Prompt completo:

```text
Use case: ui-mockup.
Asset type: design exploration for C-OS (Commodore OS), an operating system for C64 Ultimate.
Create ONE full-screen desktop UI mockup, not a photo or a monitor scene. Output a landscape 1280 x 800 image representing a 320 x 200 logical pixel screen enlarged exactly 4x with nearest-neighbour pixel edges. Everything must look possible on a REAL low resolution 320x200 display: tiny but readable 5x7 bitmap letters in 6x8 cells; crisp integer-sized pixels; one-pixel borders; very few controls; restrained spacing. No high-resolution typography pretending to be pixel art.
Use ONLY these five flat neutral colors for everything: black #000000, white #FFFFFF, dark gray #555555, middle gray #888888, light gray #BBBBBB. No other colors, gradients, blur, antialiasing, smooth shadows, CRT effects, photography, perspective, outer device frame, captions outside the desktop, Apple/Windows/NeXT logos or watermarks.
C-OS text must be spelled exactly. Original tiny hand-designed pixel icons. Empty calm desktop with launchers and small widgets, NO open application windows, no fake screenshots of modern apps. This is a functional period-inspired desktop, not a decorative retro poster. Keep most of the desktop completely empty.
Variant A: compact classic Macintosh / Windows 95 inspired desktop, adapted to this tiny display. Solid middle-gray desktop background. Four small traditional desktop icons in a single column at left, at logical x=14 and y=12, 50, 88, 126: a folder labeled "Files", a document labeled "Note", a tiny command screen labeled "Term", and a gear labeled "Setup". Icon drawings are about 20x20 logical pixels, with their short white labels directly below on gray. Bottom taskbar exactly 16 logical pixels high: light gray with a white top bevel and black lower outline, a compact left button "C-OS", one small recessed central field reading "Pronto", and right clock "12:34". Sharp understated two-tone bevels like early Windows. A small black-and-white arrow cursor near the center-right. No top menubar. Desktop emptiness and practical scale matter.
```

## B next-dock

Immagine: [B-next-dock.png](mockups/B-next-dock.png)

Prompt completo:

```text
Use case: ui-mockup.
Asset type: design exploration for C-OS (Commodore OS), an operating system for C64 Ultimate.
Create ONE full-screen desktop UI mockup, not a photo or a monitor scene. Output a landscape 1280 x 800 image representing a 320 x 200 logical pixel screen enlarged exactly 4x with nearest-neighbour pixel edges. Everything must look possible on a REAL low resolution 320x200 display: tiny but readable 5x7 bitmap letters in 6x8 cells; crisp integer-sized pixels; one-pixel borders; very few controls; restrained spacing. No high-resolution typography pretending to be pixel art.
Use ONLY these five flat neutral colors for everything: black #000000, white #FFFFFF, dark gray #555555, middle gray #888888, light gray #BBBBBB. No other colors, gradients, blur, antialiasing, smooth shadows, CRT effects, photography, perspective, outer device frame, captions outside the desktop, Apple/Windows/NeXT logos or watermarks.
C-OS text must be spelled exactly. Original tiny hand-designed pixel icons. Empty calm desktop with launchers and small widgets, NO open application windows, no fake screenshots of modern apps. This is a functional period-inspired desktop, not a decorative retro poster. Keep most of the desktop completely empty.
Variant B: NeXTSTEP-inspired square dock desktop. No taskbar and no top menu bar. Solid middle-gray desktop. A single tightly arranged vertical dock near the RIGHT edge, five square 32x32 logical-pixel tiles, with 2 logical pixels spacing and a tiny margin. Original bold black/white/light-gray beveled tiles, close to NeXT's austere visual language without copying a logo. Top four app tiles have integrated short bitmap labels, not labels floating outside: "Files" with a folder, "Note" with paper and pen, "Term" with a >_ terminal, "Setup" with a gear. Fifth bottom tile is an analog clock widget showing 12:34 with a small label "12:34". Each icon is coarse pixel art that truly fits inside a 32x32 tile, no tiny elaborate details. At top left only the small text "C-OS" in a black rectangular plaque about 36x12 logical pixels, no full-width bar. The rest of the desktop is empty gray. A black-and-white arrow cursor near the middle. This should make the contrast with conventional desktop taskbar immediately visible.
```

## C next-libero

Immagine: [C-next-libero.png](mockups/C-next-libero.png)

Prompt completo:

```text
Use case: ui-mockup.
Asset type: design exploration for C-OS (Commodore OS), an operating system for C64 Ultimate.
Create ONE full-screen desktop UI mockup, not a photo or a monitor scene. Output a landscape 1280 x 800 image representing a 320 x 200 logical pixel screen enlarged exactly 4x with nearest-neighbour pixel edges. Everything must look possible on a REAL low resolution 320x200 display: tiny but readable 5x7 bitmap letters in 6x8 cells; crisp integer-sized pixels; one-pixel borders; very few controls; restrained spacing. No high-resolution typography pretending to be pixel art.
Use ONLY these five flat neutral colors for everything: black #000000, white #FFFFFF, dark gray #555555, middle gray #888888, light gray #BBBBBB. No other colors, gradients, blur, antialiasing, smooth shadows, CRT effects, photography, perspective, outer device frame, captions outside the desktop, Apple/Windows/NeXT logos or watermarks.
C-OS text must be spelled exactly. Original tiny hand-designed pixel icons. Empty calm desktop with launchers and small widgets, NO open application windows, no fake screenshots of modern apps. This is a functional period-inspired desktop, not a decorative retro poster. Keep most of the desktop completely empty.
Variant C: ultra-minimal NeXT-inspired desktop with freely arranged square launch tiles and widgets, NO persistent dock, NO taskbar, NO top menubar. Solid middle-gray desktop. Four beveled square 32x32 logical-pixel app tiles in a compact 2x2 cluster at top-left, with 4-pixel gaps, beginning at logical x=8 y=8. The tiles contain chunky readable icons and integrated short labels: "Files", "Note", "Term", "Setup". At top-right, separate from the app cluster, a single 32x32 analog clock widget with integrated label "12:34". Directly below that a matching 32x32 tiny monochrome system meter widget: large "REU" label and three simple horizontal memory bars, no tiny numbers. Almost all of the lower two-thirds and central area are empty gray. A small discreet "C-OS" bitmap word at bottom-left, no panel behind it. Original chunky black/white/light-gray icon drawings, dark edges, subtle one-pixel raised bevels. Black-and-white arrow cursor near the center. Calm, austere, spatial and usable, not a modern dashboard.
```
