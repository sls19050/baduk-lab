# Provenance

`xgboost20tun_booster.json` and `xgboost20tun_residual_calibrator.json` are
vendored, unmodified, from wimi321/lizzieyzy-next:

- https://github.com/wimi321/lizzieyzy-next
- Paths: `src/main/resources/models/strength/xgboost20tun_booster.json` and
  `.../xgboost20tun_residual_calibrator.json`
- License: GNU GPLv3 (see that repo's `LICENSE.txt`)

`strength.py` (the module that loads these files) is a from-scratch Python
port of the feature-engineering and scoring logic in that repo's
`PlayerStrengthEstimator.java`, `XGBoostStrengthModel.java`, and
`XGBoost20TunResidualCalibrator.java` -- same formulas and thresholds,
reimplemented rather than translated line-by-line, but a derivative work of
GPLv3-licensed code and model weights nonetheless.

The rest of baduk-lab is MIT-licensed. This subtree is not: it and
`strength.py` are only used here because baduk-lab is run privately, which
the GPL doesn't restrict. If this repo is ever published or distributed
alongside these files, that distribution is GPLv3-encumbered regardless of
the MIT header elsewhere in the project -- either relicense this subtree's
consumers under GPLv3-compatible terms, or drop `strength.py` and this
`models/strength/` directory first.
