# Powder Flow Measurement System

## Overview

This system automatically evaluates powder flowability using a Raspberry Pi-based dispensing device.
It measures the following properties and classifies them according to standard criteria:

- Bulk density and tapped density
- Hausner Ratio and Hausner Class
- Angle of repose and repose class

Results are saved as CSV/JSON files and accumulated in the on-device Material DB for comparison across materials and runs.

---

## Connecting to the Device

Connect your computer and the Raspberry Pi to the **same local network**, then open a terminal and run:

```bash
ssh sdl-5@dispensercontroller.local
```

| Item | Value |
|------|-------|
| Hostname | `dispensercontroller.local` |
| Username | `sdl-5` |
| Password | `Let'sFormulate5` |

---

## Starting the Application

After connecting via SSH (or from a terminal on the device itself):

```bash
cd ~/powder-flow
./run_app_desktop.sh
```

This script pulls the latest code from git, activates the Python virtual environment, and launches the GUI.
The application window is 800 × 480 px and is optimized for the device's touchscreen display.

---

## Application Screens

The app has three layers:

| Screen | When shown |
|--------|-----------|
| **Tab screen** | Default; for configuration and data review |
| **Run screen** | During an automated experiment |
| **Result screen** | After an experiment finishes |

---

## Tab Screen

### Setup Mode (default tab)

Configure an experiment before running it.

| Field | Description |
|-------|-------------|
| **Material name** | Select from the dropdown or type a new name |
| **Disk ID** | Select the dispensing disk currently installed in the hardware |
| **Candidate vibration levels** | Check one or more levels (1 = weakest, 5 = strongest) |
| **Candidate vibration times** | Check one or more durations: 1 s, 2 s, or 3 s |
| **Dose count for evaluation** | Number of doses per vibration level/time combination (3–20) |
| **Dose count for stability test** | Number of doses for the stability/calibration phase (3–20) |

> All settings are saved **automatically** when changed. There is no separate Save button in Setup Mode.

Press **Start Automated Evaluation** to begin the full measurement sequence.
The screen switches to the Run screen immediately.

---

### Manual Mode

Run a single dispensing sequence with custom settings for inspection or troubleshooting.
Results from Manual Mode are **not** saved as experiment records.

| Control | Description |
|---------|-------------|
| **Vibration level** | Select one value (0–5); 0 = no vibration |
| **Vibration time** | Select one duration (1 s, 2 s, 3 s) |
| **Dose count** | Number of doses to dispense |
| **Camera focus** | Auto or Manual; manual mode requires a lens position value (0.0–32.0) |
| **Run** | Execute the manual dispensing sequence |
| **Clog Clear** | Run a clog-clearing sequence if the nozzle appears blocked |
| **Capture Image** | Take a single camera image without dispensing |

---

### Single Test Mode

Run individual measurement stages independently, using the current **Setup Mode** settings.
Useful for checking one property at a time, or for re-running a stage that failed in a full experiment.

| Button | Description |
|--------|-------------|
| **Calibration** | Measures step mass at each candidate vibration level and time |
| **Angle of Repose** | Captures and analyzes the powder pile angle |
| **Tapped Density** | Measures density after vibration compaction |
| **Bulk Density** | Measures density under gentle vibration |
| **Dispense Once** | Dispenses a single dose (useful for priming the nozzle) |
| **Capture Image** | Takes a single camera image for visual inspection |

> Update settings in Setup Mode **before** running single tests if you need different conditions.
> Results can be saved individually and are stored under `logs/experiments/single/`.

---

### Material DB

Displays all accumulated measurement results, grouped by material name.

Use the **Material** dropdown to select a material.
The table shows all records for that material, including:

- Disk ID and disk volume (mL)
- Vibration level and time used
- Step mass mean and standard deviation
- Bulk density, tapped density, Hausner Ratio, and Hausner Class
- Angle of repose and repose class

Press **Refresh** to reload after new results have been saved.

---

## Run Screen

Shown automatically after pressing **Start Automated Evaluation**.

The screen displays:
- Run datetime and elapsed time
- Current material name and disk ID
- Vibration level/time combinations under evaluation
- Live log output

**Abort** — stops the experiment immediately.
Use only if necessary; the hardware may be mid-cycle and may need to be checked manually before restarting.

After the experiment finishes, the screen transitions automatically to the Result screen.
Press **Run Same Conditions Again** if you want to repeat the same experiment without returning to Setup Mode.

---

## Result Screen

Review the result before deciding whether to keep it.

| Area | Description |
|------|-------------|
| **Summary** (left, 3 pages) | Navigate with `< >` buttons: *Success* (pass/fail per stage), *Calibration* (step mass per vib level/time), *Flowability* (densities, Hausner Ratio, angle of repose) |
| **Preview images** (right) | Images captured during the experiment; navigate with `< >` if multiple |
| **Raw JSON** | Full result data for detailed inspection |

Press **Save Results** to write the result files and update the Material DB.
Press **Discard Results** to discard the data and return to Setup Mode without saving.

> You **must** press either Save or Discard to return to the Setup screen.

---

## Output Files

| Location | Contents |
|----------|----------|
| `logs/experiments/all/<timestamp>_<material>/` | Full experiment results (CSV + JSON + images) |
| `logs/experiments/single/<timestamp>_<material>_<stage>/` | Single test results |
| `config/material_database.json` | Cumulative Material DB (updated on save) |
| `config/app_settings.json` | Current Setup Mode settings (auto-saved) |

---

## Repository Structure

```
powder-flow/
├── app/                        # GUI application code
│   ├── main.py                 # Entry point; manages screen transitions
│   ├── views/                  # One file per screen/tab
│   │   ├── setup.py            # Setup Mode
│   │   ├── run.py              # Run screen (during experiment)
│   │   ├── result.py           # Result screen (review / save / discard)
│   │   ├── manual.py           # Manual Mode
│   │   ├── single_test.py      # Single Test Mode
│   │   └── material_db.py      # Material DB
│   └── widgets/                # Reusable touch-friendly UI components
│
├── config/                     # Device configuration files
│   ├── app_settings.json       # Current Setup Mode settings (auto-updated by the app)
│   ├── disk_master.csv         # Disk ID → volume (mL) look-up table
│   ├── material_database.json  # Per-material calibration and flowability results
│   │                           #   (updated automatically on each save)
│   ├── P_calibration.csv       # Calibration export for use by external systems
│   └── P_calibration.json      #   (optimal vibration condition + step mass per material/disk)
│
├── hardware_api/               # Hardware interface modules
│   ├── balance/
│   │   └── balance_api.py      # USB balance communication
│   ├── camera/
│   │   └── camera_api.py       # Camera module interface
│   └── powder_dispenser/
│       ├── p_dispenser_api.py      # Arduino-based dispenser control (not in current use)
│       └── p_dispenser_HAT_api.py  # Raspberry Pi + Motor HAT control (current setup)
│
├── logs/                       # Experiment logs
│   └── experiments/
│       ├── all/                # Full automated experiment results
│       │   └── <timestamp>_<material>/   # One folder per run
│       ├── single/             # Single Test Mode results saved individually
│       │   └── <timestamp>_<material>_<stage>/
│       └── old/                # Results from older software versions
│
├── operation/                  # Logic layer connecting UI actions to hardware
│   ├── workflows.py            # Experiment flows called by each app mode
│   ├── powder_flow_api.py      # Measurement implementations (calibration, densities, repose)
│   ├── repose_analysis.py      # Angle-of-repose image analysis
│   ├── powder_flow_io.py       # CSV serialisation utilities
│   ├── step_timing_probe.py    # Step sensor timing diagnostic
│   ├── cli.py                  # Command-line runner for experiments
│   └── testing/                # Hardware verification scripts
│
├── output/                     # Cross-run summary CSVs (appended automatically on save)
│   ├── flowability_data.csv    # One row added per saved Automated Evaluation:
│   │                           #   bulk density, tapped density, Hausner Ratio, angle of repose
│   └── calibration_data.csv    # One row added per saved calibration result:
│                               #   optimal vibration condition, step mass mean / stdev
│
├── service/                    # Device-agnostic shared logic
│   ├── result_store.py         # Core save logic (writes logs, updates DB, appends output CSVs)
│   ├── result_writer.py        # Result → CSV conversion utilities
│   ├── settings_store.py       # app_settings.json read/write and default values
│   └── plot_service.py         # Plot generation (e.g. angle-of-repose analysis charts)
│
├── run_app.sh                  # Pulls latest code, activates venv, launches the app
└── run_app_desktop.sh          # Sets DISPLAY and calls run_app.sh (use this on the device)
```

---

## Precautions

- **Load powder and install the correct disk before starting.**
  Verify the Disk ID in Setup Mode matches the physical disk in the device before pressing Start Automated Evaluation.

- **Setup Mode settings auto-save immediately.**
  Any change to material name, disk ID, or vibration settings is written to disk instantly. Double-check your settings before starting a run.

- **Do not switch tabs or interact with Manual/Single Test Mode while a Run is in progress.**
  The automated experiment runs in a background thread; unexpected interactions may interfere with the sequence.

- **After Abort**, inspect the hardware before restarting.
  The dispenser mechanism may have stopped mid-cycle. Clear any powder or blockage manually if needed.

- **Run Calibration first for a new material or after changing the disk.**
  The flowability calculations (bulk density, tapped density) depend on calibration data stored in the Material DB.
  Without a valid calibration record, results may be unreliable.

- **Save or Discard before leaving the Result screen.**
  Closing the app without doing so will leave temporary files on disk and the Material DB will not be updated.
