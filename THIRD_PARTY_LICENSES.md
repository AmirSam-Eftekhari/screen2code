# Third-party notices

Declared licence information for direct runtime dependencies, read from the installed package metadata in the development environment. **Verify each licence text before a release;**
this table is a starting point, not legal advice.

| Package | Version | License (metadata) | Classifier | Note |
|---|---|---|---|---|
| numpy | 2.4.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |  |  |
| Pillow | 12.1.1 | MIT-CMU |  |  |
| opencv-python-headless | 4.13.0.92 | Apache 2.0 | Apache Software License | wheels bundle FFmpeg (LGPL) and other third-party libraries |
| scikit-image | 0.26.0 | Files: * | BSD License |  |
| playwright | 1.56.0 | Apache-2.0 |  | downloads Chromium separately |
| pytesseract | 0.3.13 | Apache License 2.0 | Apache Software License |  |
| click | 8.3.1 | BSD-3-Clause |  |  |
| platformdirs | 4.9.4 | MIT | MIT License |  |
| psutil | 7.2.2 | BSD-3-Clause |  |  |

External programs and assets used at runtime (not bundled): Tesseract OCR (Apache-2.0), Chromium via Playwright (BSD-style plus bundled third-party licences),
system fonts used for rendering (Liberation fonts: SIL OFL 1.1; DejaVu fonts: Bitstream Vera/Arev licence). Screen2Code bundles no model weights and no fonts.

Datasets: none are redistributed. The benchmark corpus is generated from word lists and procedural shapes in this repository.
