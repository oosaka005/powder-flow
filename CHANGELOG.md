# Changelog

## [Unreleased] - 2026-04-14

### Added
- `config/material_database.json`: new unified material database replacing `P_calibration.json`; stores calibration parameters, 1-step mass mean/stdev, bulk/tapped density, Hausner ratio, and angle of repose per `mat_name + diskID` key (no date field)
- `service/result_store._update_material_database`: merges result fields into `material_database.json`; partial updates supported (single test updates only the stage fields, preserving others)
- `service/result_store._load_disk_volume`: reads `volume_ml` from `disk_master.csv` and stores it in the material database record

### Changed
- `app/views/result._on_save`: "Update material database?" dialog now appears for all result types (previously only for calibration); uses `update_material_database` flag
- `app/views/setup._populate_material_name_candidates`: reads material names from `material_database.json` instead of `P_calibration.json`
- `service/result_store`: removed `_apply_calibration_payload` and `_update_calibration_config_json`; calibration date removed from stored records

## [Unreleased] - 2026-04-10

### Changed
- `operation/repose_analysis.py`: `crop_bottom_ratio` changed from 0.11 to 0.05 to include more of the bottom of the image in angle of repose analysis
- `operation/repose_analysis.py`: angle of repose bin selection changed to exclude top 2 and bottom 2 bins (previously top 1 and bottom 1), and `k_keep` changed from 3 to 4; uses middle 4 bins to avoid apex region bias
- `operation/repose_analysis.py`: removed `_check_apex_centered` check; the analysis already detects the apex dynamically, so the image-center offset check was inconsistent
- `operation/repose_analysis.py`, `operation/workflows.py`: preprocessing artifacts (cropped, processed) are now saved to disk immediately after preprocessing so they are available in the UI even when analysis fails
- `operation/repose_analysis.py`: `_preprocess_repose` now uses a fixed binary threshold (`binary_threshold=190`) instead of Otsu's automatic thresholding, to avoid misclassifying the faint white background as powder

## [Unreleased] - 2026-04-09

### Changed
- `config/app_settings.json`: `bulk_density.vib_sec_default` changed from 1.0 to 2.0
- `config/app_settings.json`: `bulk_density.weak_vib_level` changed from 1 to 2; `vib_sec_default` changed from 2.0 to 1.0
- `operation/powder_flow_api.py`: `measure_bulk_density` strong vibration duration changed from 2.0 to 1.0 seconds (both main and recovery path)
- `operation/repose_analysis.py`, `operation/powder_flow_api.py`: angle of repose method switched from `shoulder_baseline` (USP) to `direct_profile` (original RANSAC-based); `analyze_repose` now branches on the `method` parameter

## [Unreleased] - 2026-04-08

### Changed
- `operation/powder_flow_api.py`: Post-`_guarded_step` vibration duration changed from 1.0s to 2.0s in both `measure_bulk_density` and `measure_tapped_density` (including recovery paths)

## [Unreleased] - 2026-04-07

### Added
- Single Test Mode: Save button is now enabled for all single test results (calibration, bulk density, tapped density, angle of repose)
- Single Test Mode: results are saved under `logs/experiments/single/<timestamp>_<material>_<stage>/`
- Full experiment results are now saved under `logs/experiments/all/<run_id>/` (previously saved directly under `logs/experiments/`)
- Calibration results (both full experiment and single test) now prompt the user to optionally update `P_calibration.json` at save time
- New CSV outputs for single test saves:
  - `*_repose_result.csv` (angle_deg, class, success)
  - `*_bulk_density_raw.csv` / `*_tapped_density_raw.csv` (index, mass_g, density_g_per_ml for all measurements)
  - `*_bulk_density_summary.csv` / `*_tapped_density_summary.csv` (mean, stdev, n_total, n_used)
- All single test saves include a `result.json` with the full raw result data

### Changed
- `service/result_store.py`: `save_results()` now writes to `all/` subdirectory; calibration config update is gated on user confirmation
- `app/views/result.py`: Save button enabled for single test results; calibration popup added to save flow
- `app/main.py`: `save_single_test_requested` signal connected to new `save_single_test_result()` handler
- `app/views/result.py`: Full experiment result view redesigned — Raw JSON panel removed; summary split into 3 paged sections (Success / Calibration / Flowability) navigated via `< / >` buttons; images from all stages shown together on the right with caption and navigation; number formatting updated (Mean Step Mass `.3f`, Step Mass Std `.4f`, Angle of Repose `.2f°` with class, densities and Hausner Ratio `.3f` with class); layout changed to 50/50 left/right split
