# Benchmark run `smoke-seed1-f53562e80c29`

- valid: **True**
- dataset 0.1.0 / tier smoke / scenes 8 / seed 1
- browser: chromium 141.0.7390.37  (chromium sandbox: False)
- OCR: {'id': 'ocr.tesseract', 'lang': 'eng', 'version': 'tesseract 5.3.4'}
- duration: 44.7 s

## Structure metrics vs ground truth (mean, 95% bootstrap CI)

| metric | mean | CI95 | n |
|---|---|---|---|
| precision | 0.8884 | (0.8477, 0.9261) | 8 |
| recall | 0.8041 | (0.7293, 0.8796) | 8 |
| recall_text | 0.9904 | (0.9712, 1.0) | 8 |
| recall_container_visible | 0.9286 | (0.7857, 1.0) | 7 |
| recall_container | 0.5144 | (0.3052, 0.7165) | 8 |
| recall_image | 1.0 | (1.0, 1.0) | 1 |
| text_cer | 0.0303 | (0.0, 0.0899) | 8 |
| text_exact | 0.939 | (0.8348, 1.0) | 8 |
| font_size_within_1px | 0.9271 | (0.8333, 1.0) | 8 |
| font_size_mae_px | 0.5882 | (0.3259, 0.9003) | 8 |
| weight_accuracy | 0.9405 | (0.8705, 1.0) | 8 |
| fill_de | 0.0853 | (0.0, 0.256) | 7 |
| layout_accuracy | 0.925 | (0.8417, 1.0) | 6 |

## Visual metrics (pipeline output vs reference)

| metric | mean | CI95 |
|---|---|---|
| ssim | 0.9612 | (0.9409, 0.9762) |
| edge_f1 | 0.8507 | (0.7327, 0.9584) |
| pixel_mismatch | 0.032 | (0.0121, 0.0658) |
| layout_mean_iou | 0.8251 | (0.7638, 0.8812) |
| composite | 0.8996 | (0.8512, 0.9421) |

## Baselines (why pixel metrics alone are insufficient)

| baseline | SSIM | edge F1 | pixel mismatch | structure recall |
|---|---|---|---|---|
| blank page | 0.7255 | 0.0 | 0.3168 | 0.0 |
| single `<img>` of the screenshot | 1.0 | 1.0 | 0.0 | 0.0 |
| **Screen2Code** | 0.9612 | 0.8507 | 0.032 | 0.8041 |

## By category

| category | scenes | SSIM | recall | text CER |
|---|---|---|---|---|
| landing | 1 | 0.9448 | 0.9583 | 0.0036 |
| cards | 1 | 0.9768 | 0.8571 | 0.0 |
| form | 1 | 0.9714 | 0.6923 | 0.0 |
| navbar | 1 | 0.9795 | 0.7692 | 0.0 |
| dashboard | 1 | 0.9717 | 0.7727 | 0.2386 |
| multicolumn | 1 | 0.9824 | 0.6364 | 0.0 |
| typography | 1 | 0.9656 | 0.7778 | 0.0 |
| ecommerce | 1 | 0.8972 | 0.9688 | 0.0 |

## Determinism

- repeat check: {'checked': True, 'all_identical': True}

## Limitations

- synthetic scenes are cleaner and more regular than real sites; results do not predict real-world performance
- scenes use the same font family as the generation font policy, so typography results are optimistic
- the corpus emitter is independent of the product generator, but both run in the same Chromium and font environment
